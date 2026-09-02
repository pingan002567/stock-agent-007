from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.channels.binding import BindingStore
    from backend.channels.service import ChannelService
from dataclasses import dataclass
from pathlib import Path

from backend import paths
from backend.agent_runtime.deerflow_client import DeerFlowClientAdapter
from backend.agent_runtime import tools as workbench_tools
from backend.agent_runtime.result_normalizer import ResultNormalizer
from backend.agent_runtime.skill_registry import SkillRegistry
from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
from backend.app_services.audit_service import AuditService
from backend.app_services.context_builder import ContextBuilder
from backend.app_services.copilot_context_builder import CopilotContextBuilder
from backend.app_services.copilot_service import CopilotService
from backend.app_services.decision_journal_service import DecisionJournalService
from backend.app_services.execution_policy import ExecutionPolicy
from backend.app_services.intent_router import IntentRouter
from backend.app_services.data_collector_service import DataCollectorService
from backend.app_services.monitor_service import MonitorService
from backend.app_services.paper_portfolio_service import PaperPortfolioService
from backend.app_services.paper_trading_service import PaperTradingService
from backend.app_services.pre_trade_review_service import PreTradeReviewService
from backend.app_services.permission_guard import PermissionGuard
from backend.app_services.rebalance_draft_service import RebalanceDraftService
from backend.app_services.report_service import ReportService
from backend.app_services.review_inbox_service import ReviewInboxService
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.app_services.runtime_observer import runtime_observer, RuntimeObserver
from backend.app_services.strategy_service import StrategyService
from backend.app_services.task_service import TaskService
from backend.app_services.tool_execution_service import ToolExecutionService
from backend.app_services.llm_provider_service import LlmProviderService
from backend.config.data_sources import DEFAULT_DATA_SOURCES
from backend.config.runtime import DEFAULT_RUNTIME_CONFIG
from backend.stock_domain.multi_providers import create_provider
from backend.persistence.db import connect
from backend.persistence.file_store import FileStore
from backend.persistence.repositories import WorkbenchRepository


@dataclass
class AppServices:
    repo: WorkbenchRepository
    data_collector: DataCollectorService
    context_builder: ContextBuilder
    copilot_context_builder: CopilotContextBuilder
    audit_service: AuditService
    task_service: TaskService
    report_service: ReportService
    risk_policy_service: RiskPolicyService
    copilot_service: CopilotService
    scheduler_service: "SchedulerService"
    monitor_service: MonitorService
    strategy_service: StrategyService
    rebalance_draft_service: RebalanceDraftService
    pre_trade_review_service: PreTradeReviewService
    paper_trading_service: PaperTradingService
    paper_portfolio_service: PaperPortfolioService
    decision_journal_service: DecisionJournalService
    review_inbox_service: ReviewInboxService
    permission_guard: PermissionGuard
    tool_execution_service: ToolExecutionService
    runtime_observer: RuntimeObserver
    channel_service: "ChannelService"
    channel_binding_store: "BindingStore"
    llm_provider_service: "LlmProviderService"


_log = logging.getLogger("bootstrap")


def _seed_disabled() -> bool:
    """Skip network-dependent seeding/warmup when WORKBENCH_SKIP_SEED is truthy."""
    return os.getenv("WORKBENCH_SKIP_SEED", "").strip().lower() in {"1", "true", "yes"}


def _seed_market_data(repo: WorkbenchRepository, provider_router) -> None:
    """First-run data seeding + background warmup.

    Side-effecting and network-dependent: starts the primary provider's background
    refresh, auto-imports A-share/HK/US master lists when missing, and warms hot-stock
    caches on a daemon thread. Safe to skip — the app functions without it (just with a
    cold cache and empty master table until manually imported).
    """
    if hasattr(provider_router.primary, "start_background_refresh"):
        provider_router.primary.start_background_refresh(interval_seconds=300)

    primary_available = provider_router.primary.is_available()
    if not primary_available:
        return

    # Auto-import A-share master when the table is empty.
    if not repo.list_stock_master():
        try:
            from backend.stock_domain.catalog_tools import import_a_share_master

            result = import_a_share_master()
            if result.get("ok"):
                _log.info("imported %d A-share stocks", result["imported"])
        except Exception:
            _log.exception("A-share master import failed")

    def _warmup():
        try:
            provider_router.warmup_hot_stocks()
        except Exception:
            pass

    threading.Thread(target=_warmup, name="stock-warmup", daemon=True).start()

    # 行业映射回填（东财行业成分股反向索引，约 86 次请求）：
    # 后台线程执行，TTL 7 天内幂等跳过，不阻塞启动。
    def _sync_industry():
        try:
            from backend.stock_domain.industry_tools import sync_industry_mapping

            result = sync_industry_mapping()
            if result.get("ok") and not result.get("skipped"):
                _log.info(
                    "industry mapping: %s symbols mapped, %s rows updated",
                    result.get("mapped"), result.get("updated"),
                )
        except Exception:
            _log.exception("industry mapping sync failed")

    threading.Thread(target=_sync_industry, name="industry-sync", daemon=True).start()

    # Auto-import HK/US master lists when those markets are missing.
    existing_markets = {s.market for s in repo.list_stock_master(active_only=True)}
    try:
        from backend.stock_domain.catalog_tools import (
            import_hk_stock_master,
            import_us_stock_master,
        )

        if "HK" not in existing_markets:
            hk_result = import_hk_stock_master()
            if hk_result.get("ok"):
                _log.info("imported %d HK stocks", hk_result["imported"])

        if "US" not in existing_markets:
            us_result = import_us_stock_master()
            if us_result.get("ok"):
                _log.info("imported %d US stocks", us_result["imported"])
    except Exception:
        _log.exception("HK/US master import failed")


def ensure_workspace_files() -> None:
    """工作目录档案文件保障（幂等）：

    1. ``workspace.json``：档案元信息（名称/创建时间/schema 版本）——多工作区
       切换器的显示名与将来数据迁移的版本依据。
    2. ``extensions_config.json``（MCP 服务器配置）：用户配置属于工作目录。
       历史位置在仓库根——首次运行时做一次性拷贝迁移；两处都没有则写空配置
       （DeerFlow 在显式指定路径时要求文件存在）。随后经
       ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` 把本进程内所有读写（含 embedded
       DeerFlow harness）统一指到工作目录；已显式设置该 env 时尊重外部值。
    """
    import json
    from datetime import datetime, timezone

    data_dir = paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    meta = paths.workspace_meta_path()
    if not meta.exists():
        # 目录名作默认档案名；桌面默认位置 …/StockAgent/data 取父级名更可读
        name = data_dir.name if data_dir.name != "data" else data_dir.parent.name
        meta.write_text(json.dumps({
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    mcp_target = paths.extensions_config_path()
    if not mcp_target.exists():
        legacy = paths.REPO_ROOT / "extensions_config.json"
        if legacy.is_file():
            mcp_target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            _log.info("migrated extensions_config.json into workspace: %s", mcp_target)
        else:
            mcp_target.write_text('{\n  "mcpServers": {}\n}\n', encoding="utf-8")
    os.environ.setdefault("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(mcp_target))


def create_services(
    db_path: str | Path | None = None,
    files_root: str | Path | None = None,
) -> AppServices:
    if db_path is None:
        db_path = paths.default_db_path()
    if files_root is None:
        files_root = paths.default_files_root()
    ensure_workspace_files()
    repo = WorkbenchRepository(connect(db_path))
    repo.seed_defaults()
    runtime_observer.configure(repo)
    from backend.stock_domain import catalog as stock_catalog
    from backend.stock_domain.provider_router import (
        provider_router as stock_provider_router,
    )

    stock_catalog.set_repo(repo)
    stock_provider_router.repo = repo
    from backend.stock_domain import provider_credentials

    def _resolve_provider_credential(provider_id: str, field: str) -> str | None:
        config = repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
        creds = config.get("provider_credentials") or {}
        block = creds.get(provider_id) if isinstance(creds, dict) else None
        if isinstance(block, dict):
            value = block.get(field)
            if value:
                return str(value)
        return None

    provider_credentials.set_credential_resolver(_resolve_provider_credential)
    # Ensure data_sources config is seeded (mock 会被清洗为真实默认 provider)
    from backend.config.data_source_sanitize import sanitize_data_sources

    seeded = sanitize_data_sources(repo.get_config("data_sources", DEFAULT_DATA_SOURCES))
    if seeded != repo.get_config("data_sources", DEFAULT_DATA_SOURCES):
        repo.set_config("data_sources", seeded)
    else:
        repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
    # Wire up intel router
    from backend.config.intel_sources import DEFAULT_INTEL_SOURCES
    from backend.stock_domain.intel_providers import intel_router as stock_intel_router

    stock_intel_router.repo = repo
    from backend.config.data_source_sanitize import sanitize_intel_sources

    intel_seeded = sanitize_intel_sources(repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES))
    if intel_seeded != repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES):
        repo.set_config("intel_sources", intel_seeded)
    else:
        repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES)
    # Network-dependent seeding + cache warmup. Kept out of the construction path so
    # `create_services()` stays cheap and offline-safe; gate with WORKBENCH_SKIP_SEED=1
    # (set in tests) to avoid touching the network during boot.
    if not _seed_disabled():
        _seed_market_data(repo, stock_provider_router)
    file_store = FileStore(files_root)
    context_builder = ContextBuilder(repo)
    audit_service = AuditService(repo)
    task_service = TaskService(repo)
    permission_guard = PermissionGuard()
    tool_execution_service = ToolExecutionService(repo)
    risk_policy_service = RiskPolicyService(repo, audit_service)
    strategy_service = StrategyService(repo, audit_service, risk_policy_service)
    monitor_service = MonitorService(
        repo=repo,
        context_builder=context_builder,
        audit_service=audit_service,
        risk_policy_service=risk_policy_service,
    )
    data_collector = DataCollectorService(repo=repo)
    paper_portfolio_service = PaperPortfolioService(
        repo=repo, audit_service=audit_service
    )
    decision_journal_service = DecisionJournalService(
        repo=repo,
        audit_service=audit_service,
        paper_portfolio_service=paper_portfolio_service,
    )
    rebalance_draft_service = RebalanceDraftService(
        repo=repo,
        context_builder=context_builder,
        audit_service=audit_service,
        risk_policy_service=risk_policy_service,
        decision_journal_service=decision_journal_service,
    )
    pre_trade_review_service = PreTradeReviewService(
        repo=repo,
        audit_service=audit_service,
        rebalance_draft_service=rebalance_draft_service,
        risk_policy_service=risk_policy_service,
        decision_journal_service=decision_journal_service,
    )
    paper_trading_service = PaperTradingService(
        repo=repo,
        audit_service=audit_service,
        pre_trade_review_service=pre_trade_review_service,
        decision_journal_service=decision_journal_service,
    )
    report_service = ReportService(
        repo=repo,
        context_builder=context_builder,
        monitor_service=monitor_service,
        strategy_service=strategy_service,
        audit_service=audit_service,
        file_store=file_store,
        decision_journal_service=decision_journal_service,
    )
    review_inbox_service = ReviewInboxService(
        repo=repo,
        rebalance_draft_service=rebalance_draft_service,
        pre_trade_review_service=pre_trade_review_service,
        monitor_service=monitor_service,
        paper_portfolio_service=paper_portfolio_service,
    )
    copilot_context_builder = CopilotContextBuilder(
        repo=repo,
        context_builder=context_builder,
        monitor_service=monitor_service,
        risk_policy_service=risk_policy_service,
        review_inbox_service=review_inbox_service,
    )
    # 分层合成：档案 DB 覆盖 > 用户级 credentials.json > env（见 config/credentials.py）
    from backend.config.credentials import effective_runtime_config

    runtime_config = effective_runtime_config(repo)
    execution_policy = ExecutionPolicy()
    tool_bridge = WorkbenchToolBridge(
        context_builder=context_builder,
        repo=repo,
        monitor_service=monitor_service,
        risk_policy_service=risk_policy_service,
        strategy_service=strategy_service,
        rebalance_draft_service=rebalance_draft_service,
        pre_trade_review_service=pre_trade_review_service,
        paper_trading_service=paper_trading_service,
        paper_portfolio_service=paper_portfolio_service,
        report_service=report_service,
        decision_journal_service=decision_journal_service,
        review_inbox_service=review_inbox_service,
        permission_guard=permission_guard,
        tool_execution_service=tool_execution_service,
        execution_policy=execution_policy,
    )
    workbench_tools.init_workbench_tools(tool_bridge)
    copilot_service = CopilotService(
        repo=repo,
        context_builder=context_builder,
        copilot_context_builder=copilot_context_builder,
        intent_router=IntentRouter(),
        permission_guard=permission_guard,
        task_service=task_service,
        audit_service=audit_service,
        deerflow=DeerFlowClientAdapter.from_env(
            tool_bridge=tool_bridge, runtime_config=runtime_config
        ),
        skill_registry=SkillRegistry(),
        result_normalizer=ResultNormalizer(),
        runtime_observer=runtime_observer,
    )
    # IM channel layer (Telegram/Slack): bridges inbound IM → CopilotService and
    # pushes monitor alerts back out. Idle unless channels are configured.
    from backend.channels.service import build_channel_service

    channel_service, channel_binding_store, channel_notifier = build_channel_service(
        repo=repo, copilot_service=copilot_service
    )
    monitor_service.alert_sink = channel_notifier.push

    # 定时任务:按日程自动发起 Copilot run(盘前简报/周度复盘)
    from backend.app_services.scheduler_service import SchedulerService

    scheduler_service = SchedulerService(
        repo=repo, copilot_service=copilot_service, audit_service=audit_service
    )

    llm_provider_service = LlmProviderService(
        repo=repo, copilot_service=copilot_service
    )
    copilot_service.llm_provider_service = llm_provider_service

    # Cleanup old logs on startup
    try:
        deleted = repo.cleanup_provider_call_logs(keep_days=7)
        if deleted:
            import logging
            logging.getLogger("bootstrap").info("Cleaned %d old provider_call_log entries", deleted)
    except Exception:
        pass
    return AppServices(
        repo=repo,
        data_collector=data_collector,
        context_builder=context_builder,
        copilot_context_builder=copilot_context_builder,
        audit_service=audit_service,
        task_service=task_service,
        report_service=report_service,
        risk_policy_service=risk_policy_service,
        copilot_service=copilot_service,
        scheduler_service=scheduler_service,
        llm_provider_service=llm_provider_service,
        monitor_service=monitor_service,
        strategy_service=strategy_service,
        rebalance_draft_service=rebalance_draft_service,
        pre_trade_review_service=pre_trade_review_service,
        paper_trading_service=paper_trading_service,
        paper_portfolio_service=paper_portfolio_service,
        decision_journal_service=decision_journal_service,
        review_inbox_service=review_inbox_service,
        permission_guard=permission_guard,
        tool_execution_service=tool_execution_service,
        runtime_observer=runtime_observer,
        channel_service=channel_service,
        channel_binding_store=channel_binding_store,
    )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
from backend.app_services.worldcup_service import WorldCupService
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
    worldcup_service: WorldCupService


def create_services(
    db_path: str | Path = "data/workbench.sqlite3",
    files_root: str | Path = "data/files",
) -> AppServices:
    repo = WorkbenchRepository(connect(db_path))
    repo.seed_defaults()
    runtime_observer.configure(repo)
    from backend.stock_domain import catalog as stock_catalog
    from backend.stock_domain.provider_router import (
        provider_router as stock_provider_router,
    )

    stock_catalog.set_repo(repo)
    stock_provider_router.repo = repo
    # Ensure data_sources config is seeded
    repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
    # Wire up intel router
    from backend.config.intel_sources import DEFAULT_INTEL_SOURCES
    from backend.stock_domain.intel_providers import intel_router as stock_intel_router

    stock_intel_router.repo = repo
    repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES)
    if hasattr(stock_provider_router.primary, "start_background_refresh"):
        stock_provider_router.primary.start_background_refresh(interval_seconds=300)
    # Auto-import stocks from AKShare when master table is empty
    _primary_available = stock_provider_router.primary.is_available()

    if _primary_available and not repo.list_stock_master():
        try:
            from backend.stock_domain.catalog_tools import import_a_share_master

            result = import_a_share_master()
            if result.get("ok"):
                import logging

                logging.getLogger("bootstrap").info(
                    "imported %d A-share stocks", result["imported"]
                )
        except Exception:
            import logging

            logging.getLogger("bootstrap").exception("A-share master import failed")

    if _primary_available:
        import threading as _threading

        def _warmup():
            try:
                stock_provider_router.warmup_hot_stocks()
            except Exception:
                pass

        _threading.Thread(target=_warmup, name="stock-warmup", daemon=True).start()

    # Auto-import HK/US stocks if primary is available
    if _primary_available:
        existing_markets = {s.market for s in repo.list_stock_master(active_only=True)}
        try:
            from backend.stock_domain.catalog_tools import (
                import_hk_stock_master,
                import_us_stock_master,
            )

            if "HK" not in existing_markets:
                hk_result = import_hk_stock_master()
                if hk_result.get("ok"):
                    import logging

                    logging.getLogger("bootstrap").info(
                        "imported %d HK stocks", hk_result["imported"]
                    )

            if "US" not in existing_markets:
                us_result = import_us_stock_master()
                if us_result.get("ok"):
                    import logging

                    logging.getLogger("bootstrap").info(
                        "imported %d US stocks", us_result["imported"]
                    )
        except Exception:
            import logging

            logging.getLogger("bootstrap").exception("HK/US master import failed")
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
    worldcup_service = WorldCupService(repo=repo)
    copilot_context_builder = CopilotContextBuilder(
        repo=repo,
        context_builder=context_builder,
        monitor_service=monitor_service,
        risk_policy_service=risk_policy_service,
        review_inbox_service=review_inbox_service,
    )
    runtime_config = repo.get_config("runtime", {"config": DEFAULT_RUNTIME_CONFIG}).get(
        "config", DEFAULT_RUNTIME_CONFIG
    )
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
        worldcup_service=worldcup_service,
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
        worldcup_service=worldcup_service,
    )

"""Workbench tool wrappers for DeerFlow `use:` reflection registration.

Each module-level variable is a StructuredTool that delegates to
WorkbenchToolBridge.execute() at call time.  The bridge reference is injected
once at bootstrap via init_workbench_tools() — before that, tools raise.

Usage in config.yaml (tools section):
```yaml
- name: get_stock_context
  group: workbench
  use: backend.agent_runtime.tools:get_stock_context
```
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.schemas import AuthorityLevel


# ── ContextVar bridge reference (thread/coroutine-safe, injected at bootstrap) ──

import contextvars
import json as _json

_bridge_ctx: contextvars.ContextVar = contextvars.ContextVar("workbench_bridge")
# Current run attribution (run_id / task_id / source_mode / authority_level), set
# per DeerFlowClient.stream() so real-mode tool executions are attributed in the
# ledger and enforce the request authority (not just the tool's declared one).
_run_ctx: contextvars.ContextVar = contextvars.ContextVar("workbench_run_ctx", default=None)


def set_bridge(bridge: Any) -> None:
    """注入 bridge，线程/协程安全。每次 DeerFlowClient.stream() 调用前设置。"""
    _bridge_ctx.set(bridge)


def set_run_context(
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    source_mode: str | None = None,
    authority_level: str | None = None,
) -> None:
    """Set the current run attribution for real-mode tool execution (per stream)."""
    _run_ctx.set({
        "run_id": run_id,
        "task_id": task_id,
        "source_mode": source_mode,
        "authority_level": authority_level,
    })


def _get_run_context() -> dict:
    return _run_ctx.get(None) or {}


def _get_bridge() -> Any:
    """获取当前上下文的 bridge。"""
    bridge = _bridge_ctx.get(None)
    if bridge is None:
        raise RuntimeError(
            "Workbench bridge not initialised — call init_workbench_tools(bridge) "
            "or set_bridge(bridge) before using workbench tools."
        )
    return bridge


def init_workbench_tools(bridge: Any) -> None:
    """兼容旧代码：设置 ContextVar。stub 模式也通过此函数注入。"""
    set_bridge(bridge)


# ── Pydantic input models (mirrors langchain_tools.py) ──────────────────

class StockInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")


class HistoryInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    days: int = Field(default=30, description="历史天数（默认30天）")


class IntelInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    query: str = Field(default="", description="搜索关键词")


class DraftOrderInput(BaseModel):
    symbol: str = Field(description="股票代码")
    target_weight_pct: float = Field(default=15, description="目标权重百分比")


class DraftListInput(BaseModel):
    symbol: str | None = Field(default=None, description="股票代码筛选")
    status: str | None = Field(default=None, description="草案状态筛选")
    limit: int | None = Field(default=20, description="返回条数上限")


class DraftGetInput(BaseModel):
    draft_id: str = Field(description="草案ID")


class DraftConfirmInput(BaseModel):
    draft_id: str = Field(description="待确认的拟单草案ID")
    note: str | None = Field(default=None, description="确认备注（可选）")


class DraftRejectInput(BaseModel):
    draft_id: str = Field(description="待驳回的拟单草案ID")
    note: str | None = Field(default=None, description="驳回备注（可选）")


class WatchlistAddInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    name: str | None = Field(default=None, description="股票名称（可选）")
    group_name: str | None = Field(default=None, description="分组名称（可选）")


class WatchlistRemoveInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")


class HoldingUpsertInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    name: str = Field(description="股票名称")
    quantity: float = Field(description="持仓数量（股）")
    cost: float = Field(description="成本价")
    market_value: float | None = Field(default=None, description="当前市值（可选，不提供时由系统估算 = quantity * cost）")
    weight_pct: float | None = Field(default=None, description="仓位权重百分比（可选）")


class ReviewCreateInput(BaseModel):
    draft_id: str = Field(description="已确认的拟单草案ID")


class ReviewListInput(BaseModel):
    draft_id: str | None = Field(default=None, description="草案ID筛选")
    symbol: str | None = Field(default=None, description="股票代码筛选")
    status: str | None = Field(default=None, description="审查状态筛选")
    limit: int | None = Field(default=20, description="返回条数上限")


class PaperOrderListInput(BaseModel):
    review_id: str | None = Field(default=None, description="审查ID筛选")
    draft_id: str | None = Field(default=None, description="草案ID筛选")
    symbol: str | None = Field(default=None, description="股票代码筛选")
    status: str | None = Field(default=None, description="订单状态筛选")
    limit: int | None = Field(default=20, description="返回条数上限")


class MonitorEventsInput(BaseModel):
    symbol: str | None = Field(default=None, description="股票代码筛选")
    severity: str | None = Field(default=None, description="严重级别筛选")
    limit: int | None = Field(default=10, description="返回条数上限")


class MonitorEvalInput(BaseModel):
    source: str | None = Field(default="tool", description="评估触发来源")
    force: bool | None = Field(default=False, description="是否强制绕过冷却")


class StrategyListInput(BaseModel):
    enabled: bool | None = Field(default=None, description="是否只返回启用策略")


class BacktestRunInput(BaseModel):
    strategy_id: str = Field(default="concentration-control", description="策略ID")
    period: dict[str, Any] | None = Field(default=None, description="回测周期 {days: int}")
    universe: list[str] | None = Field(default=None, description="标的列表")
    parameters: dict[str, Any] | None = Field(default=None, description="参数覆盖")


class BacktestGetInput(BaseModel):
    run_id: str | None = Field(default=None, description="回测运行ID")
    strategy_id: str | None = Field(default=None, description="策略ID（未提供run_id时取最新）")


class ReportGenerateInput(BaseModel):
    report_type: str = Field(description="报告类型（stock_research/monitor_review/strategy_backtest）")
    source_type: str = Field(description="来源类型（stock/monitor_event/backtest_run）")
    source_id: str = Field(description="来源ID 或 symbol")
    template_id: str | None = Field(default=None, description="报告模板ID")
    title: str | None = Field(default=None, description="报告标题")
    options: dict[str, Any] | None = Field(default=None, description="额外选项")


class ReportQualityInput(BaseModel):
    report_id: str = Field(description="报告ID")


class JournalListInput(BaseModel):
    symbol: str | None = Field(default=None, description="股票代码筛选")
    status: str | None = Field(default=None, description="条目状态筛选")
    source_type: str | None = Field(default=None, description="来源类型筛选")
    limit: int | None = Field(default=20, description="返回条数上限")


class JournalGetInput(BaseModel):
    entry_id: str = Field(description="决策条目ID")


class JournalSummarizeInput(BaseModel):
    symbol: str | None = Field(default=None, description="股票代码筛选")


class InboxListInput(BaseModel):
    priority: str | None = Field(default=None, description="优先级筛选（high/medium/low）")
    limit: int | None = Field(default=None, description="返回条数上限")


class InboxDismissInput(BaseModel):
    item_key: str = Field(description="待办事项的 item_key")


class InboxSnoozeInput(BaseModel):
    item_key: str = Field(description="待办事项的 item_key")
    snoozed_until: str = Field(description="稍后提醒时间（ISO 8601 格式，如 2026-06-05T12:00:00）")


class InboxDoneInput(BaseModel):
    item_key: str = Field(description="待办事项的 item_key")


class EmptyInput(BaseModel):
    pass


from backend.app_services.execution_policy import ExecutionMode
from backend.app_services.permission_guard import PermissionDenied

def _tool(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    authority: AuthorityLevel,
) -> StructuredTool:
    def _run(**kwargs: Any) -> str:
        validated = args_schema(**kwargs)
        bridge = _get_bridge()
        spec = bridge._specs[name]
        arguments = validated.model_dump()

        # Run attribution + request authority for the ledger / enforcement.
        rc = _get_run_context()
        attribution = {
            "run_id": rc.get("run_id"),
            "task_id": rc.get("task_id"),
            "source_mode": rc.get("source_mode"),
        }
        req_auth = rc.get("authority_level")
        effective_authority = AuthorityLevel(req_auth) if req_auth else authority

        policy = bridge.execution_policy.decide(name)

        if policy.mode == ExecutionMode.BLOCKED:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs,
                error=policy.reason, **attribution,
            )
            return _json.dumps({"error": policy.reason, "status": "blocked"}, ensure_ascii=False)

        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            result = {"status": "needs_confirmation", "reason": policy.reason, "next_action": policy.next_action}
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs, result=result,
                **attribution,
            )
            return _json.dumps(result, ensure_ascii=False)

        # Enforce the REQUEST authority (real mode previously only compared the tool's
        # own declared authority, so request-level limits weren't applied).
        try:
            bridge.permission_guard.require(effective_authority, spec.required_authority, name)
        except PermissionDenied as exc:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs,
                error=str(exc), **attribution,
            )
            return _json.dumps({"error": str(exc), "status": "blocked"}, ensure_ascii=False)

        try:
            result = bridge._handlers[name](arguments)
        except Exception as exc:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="failed",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs, error=str(exc),
                **attribution,
            )
            raise

        bridge._record_execution(
            tool=name, domain=spec.domain, status="succeeded",
            authority_level=spec.required_authority.value,
            arguments=arguments, evidence_refs=spec.evidence_refs, result=result,
            **attribution,
        )

        return _json.dumps(result, ensure_ascii=False, default=str)

    _run.__name__ = name
    return StructuredTool.from_function(
        func=_run,
        name=name,
        description=description,
        args_schema=args_schema,
        return_direct=False,
    )


# ── Module-level tool instances (exported for DeerFlow use: reflection) ─

# A2: Research tools
get_stock_context = _tool(
    "get_stock_context",
    "根据股票代码获取完整的个股上下文信息，包含实时行情、基本面摘要、相关情报和风险提示。",
    StockInput, AuthorityLevel.A2,
)
get_daily_history = _tool(
    "get_daily_history",
    "获取指定股票的历史K线数据，支持自定义天数。返回每日开盘价、收盘价、最高价、最低价、成交量。",
    HistoryInput, AuthorityLevel.A2,
)
search_stock_intel = _tool(
    "search_stock_intel",
    "搜索指定股票的相关情报资讯，如新闻、公告、研报摘要。",
    IntelInput, AuthorityLevel.A2,
)
add_watchlist_item = _tool(
    "add_watchlist_item",
    "添加股票到自选列表。需要提供股票代码，股票名称和分组可选。",
    WatchlistAddInput, AuthorityLevel.A2,
)
remove_watchlist_item = _tool(
    "remove_watchlist_item",
    "从自选列表中删除指定的股票。",
    WatchlistRemoveInput, AuthorityLevel.A2,
)
get_monitor_events = _tool(
    "get_monitor_events",
    "获取盯盘监控事件列表，可按股票、严重级别筛选。",
    MonitorEventsInput, AuthorityLevel.A2,
)
get_monitor_rules = _tool(
    "get_monitor_rules",
    "获取当前所有盯盘监控规则及其状态。",
    EmptyInput, AuthorityLevel.A2,
)
evaluate_monitor_rules = _tool(
    "evaluate_monitor_rules",
    "手动触发一次盯盘规则评估，检查是否需要触发监控事件。",
    MonitorEvalInput, AuthorityLevel.A2,
)
list_strategies = _tool(
    "list_strategies",
    "获取所有策略库中的策略列表。",
    StrategyListInput, AuthorityLevel.A2,
)
get_backtest_result = _tool(
    "get_backtest_result",
    "获取回测结果详情，可按回测运行ID或策略ID查询。",
    BacktestGetInput, AuthorityLevel.A2,
)
list_report_templates = _tool(
    "list_report_templates",
    "获取所有可用的报告模板列表。",
    EmptyInput, AuthorityLevel.A2,
)
generate_report = _tool(
    "generate_report",
    "生成指定类型和来源的分析报告。支持 stock_research（个股研究）、monitor_review（盯盘回顾）、strategy_backtest（策略回测）。",
    ReportGenerateInput, AuthorityLevel.A2,
)
get_report_quality = _tool(
    "get_report_quality",
    "获取报告质量检查结果。",
    ReportQualityInput, AuthorityLevel.A2,
)

# A3: Portfolio & Risk tools
get_portfolio_snapshot = _tool(
    "get_portfolio_snapshot",
    "获取当前持仓快照，包含所有持仓股票的市值、权重、盈亏。",
    EmptyInput, AuthorityLevel.A3,
)
upsert_holding = _tool(
    "upsert_holding",
    "添加或更新持仓数据。仅修改本系统数据，不涉及真实交易。需要提供股票代码、名称、持仓数量和成本价，市值和权重可选。",
    HoldingUpsertInput, AuthorityLevel.A3,
)
analyze_portfolio_risk = _tool(
    "analyze_portfolio_risk",
    "分析当前持仓风险，包含集中度风险、行业风险、单票权重预警。",
    EmptyInput, AuthorityLevel.A3,
)
get_active_risk_policy = _tool(
    "get_active_risk_policy",
    "获取当前生效的风险偏好与仓位规则策略。",
    EmptyInput, AuthorityLevel.A3,
)
list_risk_policies = _tool(
    "list_risk_policies",
    "获取所有已定义的风险策略列表。",
    EmptyInput, AuthorityLevel.A3,
)
evaluate_policy_risk = _tool(
    "evaluate_policy_risk",
    "基于当前风险策略评估持仓风险。",
    EmptyInput, AuthorityLevel.A3,
)
run_strategy_backtest = _tool(
    "run_strategy_backtest",
    "运行策略回测，返回回测结果包含收益指标、风险指标和交易信号。",
    BacktestRunInput, AuthorityLevel.A3,
)
list_pre_trade_reviews = _tool(
    "list_pre_trade_reviews",
    "获取交易前审查记录列表，可按草案ID、股票、状态筛选。",
    ReviewListInput, AuthorityLevel.A3,
)
list_paper_orders = _tool(
    "list_paper_orders",
    "获取Paper Sandbox订单列表。",
    PaperOrderListInput, AuthorityLevel.A3,
)
get_paper_portfolio = _tool(
    "get_paper_portfolio",
    "获取Paper Portfolio投影摘要，包含持仓、市值、收益。",
    EmptyInput, AuthorityLevel.A3,
)
analyze_paper_performance = _tool(
    "analyze_paper_performance",
    "分析Paper Portfolio绩效归因，包含收益分解、风险调整收益。",
    EmptyInput, AuthorityLevel.A3,
)
create_paper_portfolio_snapshot = _tool(
    "create_paper_portfolio_snapshot",
    "创建Paper Portfolio快照，固化当前投影+行情作为历史记录。",
    EmptyInput, AuthorityLevel.A3,
)
list_decision_journal = _tool(
    "list_decision_journal",
    "获取AI决策日志条目列表。",
    JournalListInput, AuthorityLevel.A3,
)
get_decision_journal_entry = _tool(
    "get_decision_journal_entry",
    "获取单条AI决策日志条目详情。",
    JournalGetInput, AuthorityLevel.A3,
)
summarize_decision_outcomes = _tool(
    "summarize_decision_outcomes",
    "汇总AI决策结果，分析调仓建议执行效果。",
    JournalSummarizeInput, AuthorityLevel.A3,
)
list_review_inbox = _tool(
    "list_review_inbox",
    "获取人工审查待办列表。",
    InboxListInput, AuthorityLevel.A3,
)
summarize_review_inbox = _tool(
    "summarize_review_inbox",
    "获取审查待办摘要（按优先级分类计数）。",
    EmptyInput, AuthorityLevel.A3,
)
dismiss_inbox_item = _tool(
    "dismiss_inbox_item",
    "忽略收件箱中的一条待办事项。需要提供 item_key。",
    InboxDismissInput, AuthorityLevel.A3,
)
snooze_inbox_item = _tool(
    "snooze_inbox_item",
    "稍后提醒一条待办事项。需要提供 item_key 和 snoozed_until（ISO 8601 时间格式）。",
    InboxSnoozeInput, AuthorityLevel.A3,
)
mark_inbox_item_done = _tool(
    "mark_inbox_item_done",
    "标记收件箱中的一条待办事项为已完成。需要提供 item_key。",
    InboxDoneInput, AuthorityLevel.A3,
)

# A4: Planner tools
generate_draft_order = _tool(
    "generate_draft_order",
    "生成拟单草案，指定股票代码和目标权重，返回草案详情。",
    DraftOrderInput, AuthorityLevel.A4,
)
list_rebalance_drafts = _tool(
    "list_rebalance_drafts",
    "获取拟单草案列表。",
    DraftListInput, AuthorityLevel.A4,
)
get_rebalance_draft = _tool(
    "get_rebalance_draft",
    "获取单条拟单草案详情。",
    DraftGetInput, AuthorityLevel.A4,
)
confirm_rebalance_draft = _tool(
    "confirm_rebalance_draft",
    "确认拟单草案，将草案状态从 pending_user_confirmation 变为 confirmed_no_execution。需要显式提供待确认的草案ID，可选附带备注。确认后即可基于该草案创建交易前审查。",
    DraftConfirmInput, AuthorityLevel.A4,
)
reject_rebalance_draft = _tool(
    "reject_rebalance_draft",
    "驳回想单草案，将草案状态从 pending_user_confirmation 变为 rejected。需要显式提供待驳回的草案ID，可选附带备注。",
    DraftRejectInput, AuthorityLevel.A4,
)
create_pre_trade_review = _tool(
    "create_pre_trade_review",
    "对已确认的拟单草案创建交易前审查，检查是否符合风险策略。需要显式提供已确认的草案ID。",
    ReviewCreateInput, AuthorityLevel.A4,
)

# A5: Execution (blocked)
place_real_order = _tool(
    "place_real_order",
    "⚠️ 真实交易下单 — 当前版本已禁用，所有下单操作只能通过Paper Sandbox进行。",
    StockInput, AuthorityLevel.A5,
)


# ── Lookup helper for config generation ─────────────────────────────────

def get_all_workbench_tools() -> list[StructuredTool]:
    """Return all module-level tool instances for config registration."""
    result: list[StructuredTool] = []
    for name, obj in list(globals().items()):
        if name.startswith("_"):
            continue
        if isinstance(obj, StructuredTool):
            result.append(obj)
    return result


# ── World Cup prediction tools ─────────────────────────────────────────

class WorldCupMatchInput(BaseModel):
    match_id: str | None = Field(default=None, description="比赛ID（可选，不提供则返回所有比赛）")
    stage: str | None = Field(default=None, description="比赛阶段筛选（group/round16/quarter/semi/final）")
    status: str | None = Field(default=None, description="比赛状态筛选（upcoming/live/finished）")


class WorldCupOddsInput(BaseModel):
    match_id: str = Field(description="比赛ID")


class WorldCupPredictionInput(BaseModel):
    match_id: str = Field(description="比赛ID")
    home_score: int = Field(description="预测主队比分")
    away_score: int = Field(description="预测客队比分")
    confidence: float = Field(default=0.5, description="预测信心度 (0-1)")


class WorldCupBetInput(BaseModel):
    match_id: str = Field(description="比赛ID")
    bet_type: str = Field(description="投注类型（home/draw/away/over_2_5/under_2_5）")
    odds: float = Field(description="赔率")
    stake: float = Field(description="投注金额")
    probability: float = Field(description="真实概率 (0-100)")


class WorldCupBetUpdateInput(BaseModel):
    bet_id: str = Field(description="投注记录ID")
    status: str = Field(description="新状态（won/lost/pending）")
    profit: float | None = Field(default=None, description="盈亏金额（可选）")


class WorldCupBetDeleteInput(BaseModel):
    bet_id: str = Field(description="投注记录ID")


class WorldCupAnalysisInput(BaseModel):
    match_id: str = Field(description="比赛ID")


# World Cup tools
get_worldcup_matches = _tool(
    "get_worldcup_matches",
    "获取世界杯比赛列表。可按阶段、状态筛选。",
    WorldCupMatchInput, AuthorityLevel.A2,
)

get_worldcup_odds = _tool(
    "get_worldcup_odds",
    "获取指定比赛的赔率数据（多家博彩公司）。",
    WorldCupOddsInput, AuthorityLevel.A2,
)

get_worldcup_analysis = _tool(
    "get_worldcup_analysis",
    "获取指定比赛的详细分析，包括概率计算、价值判断、投注建议。",
    WorldCupAnalysisInput, AuthorityLevel.A2,
)

create_worldcup_prediction = _tool(
    "create_worldcup_prediction",
    "提交比赛预测（比分和信心度）。",
    WorldCupPredictionInput, AuthorityLevel.A3,
)

create_worldcup_bet = _tool(
    "create_worldcup_bet",
    "创建投注记录。",
    WorldCupBetInput, AuthorityLevel.A3,
)

update_worldcup_bet = _tool(
    "update_worldcup_bet",
    "更新投注记录状态（赢/输/待结算）。",
    WorldCupBetUpdateInput, AuthorityLevel.A3,
)

delete_worldcup_bet = _tool(
    "delete_worldcup_bet",
    "删除投注记录。",
    WorldCupBetDeleteInput, AuthorityLevel.A3,
)

list_worldcup_bets = _tool(
    "list_worldcup_bets",
    "获取投注记录列表，可按状态筛选。",
    WorldCupMatchInput, AuthorityLevel.A2,
)

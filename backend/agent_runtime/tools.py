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

from typing import Any, Literal

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
    detail: Literal["summary", "ohlc", "full"] = Field(
        default="summary",
        description=(
            "返回粒度。summary（默认）=区间涨跌/最高最低/均量/波动率/最大回撤 + 最近5根；"
            "ohlc=按 fields/limit 投影的K线；full=全量原始K线（很占上下文，仅在确需逐日数据时用）"
        ),
    )
    fields: list[str] | None = Field(
        default=None,
        description="detail=ohlc 时挑选字段，如 ['date','close']。默认 date/open/high/low/close/volume",
    )
    limit: int | None = Field(default=None, description="最多返回多少根K线（从最近往前数）")


class IntelInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    query: str = Field(default="", description="搜索关键词")
    fields: list[str] | None = Field(
        default=None,
        description="挑选字段，如 ['title','published_at']。默认 type/title/source/published_at/url",
    )
    limit: int | None = Field(default=8, description="最多返回多少条情报（默认8）")


class DraftOrderInput(BaseModel):
    symbol: str = Field(description="股票代码")
    target_weight_pct: float = Field(default=15, description="目标权重百分比")


class DraftListInput(BaseModel):
    symbol: str | None = Field(default=None, description="股票代码筛选")
    status: str | None = Field(default=None, description="草案状态筛选")
    limit: int | None = Field(default=20, description="返回条数上限")
    fields: list[str] | None = Field(
        default=None,
        description="挑选字段；默认 draft_id/symbol/status/target_weight_pct/created_at/valid_until",
    )


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
    symbol: str | None = Field(
        default=None,
        description="要删除的股票代码。与 clear_all 二选一；clear_all=true 时忽略本字段",
    )
    clear_all: bool = Field(
        default=False,
        description="是否清空全部自选（用户明确说「清空自选」时用）",
    )


class WatchlistListInput(BaseModel):
    group_name: str | None = Field(default=None, description="按分组筛选（可选）")
    monitored_only: bool = Field(default=False, description="只返回已开启盯盘的自选")
    limit: int | None = Field(default=50, description="返回条数上限（默认50）")
    fields: list[str] | None = Field(
        default=None,
        description="挑选字段；默认 symbol/name/group/monitored",
    )


class HoldingUpsertInput(BaseModel):
    symbol: str = Field(description="股票代码，如 AAPL、600519")
    name: str = Field(description="股票名称")
    quantity: float = Field(description="持仓数量（股）")
    cost: float = Field(description="成本价")
    market_value: float | None = Field(default=None, description="当前市值（可选，不提供时由系统估算 = quantity * cost）")
    weight_pct: float | None = Field(default=None, description="仓位权重百分比（可选）")


class HoldingRemoveInput(BaseModel):
    symbol: str | None = Field(
        default=None,
        description="要删除的股票代码。与 clear_all 二选一；clear_all=true 时忽略本字段",
    )
    clear_all: bool = Field(
        default=False,
        description="是否清空全部持仓（用户明确说「全部清空/清仓」时用）",
    )


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
    fields: list[str] | None = Field(
        default=None,
        description="挑选字段；默认 event_id/symbol/title/severity/trigger_rule/created_at",
    )
    include_explanation: bool = Field(
        default=False,
        description="是否附带 explanation（默认否，省上下文；需要归因时再开）",
    )


class MonitorEvalInput(BaseModel):
    source: str | None = Field(default="tool", description="评估触发来源")
    force: bool | None = Field(default=False, description="是否强制绕过冷却")


class IndustryContextInput(BaseModel):
    symbol: str | None = Field(
        default=None, description="股票代码（自动解析所属行业），如 600519"
    )
    industry: str | None = Field(
        default=None, description="行业名称（东财行业板块口径），如 酿酒行业。与 symbol 二选一"
    )


class ListDataSourcesInput(BaseModel):
    pass


class DescribeDataCapabilityInput(BaseModel):
    provider: str | None = Field(
        default=None,
        description="数据源 id，如 eastmoney / tonghuashun / tushare；可与 capability 组合",
    )
    capability: str | None = Field(
        default=None,
        description="能力名：quote/history/financial/industry_boards/industry_constituents/sectors/market_review/intel_search/cyq/moneyflow",
    )


class InvokeDataCapabilityInput(BaseModel):
    provider: str = Field(description="显式数据源 id，如 tonghuashun、tushare")
    capability: str = Field(description="能力名，如 industry_boards、quote")
    params: dict | None = Field(
        default=None,
        description="能力参数，如 {\"symbol\":\"600519\"} 或 {\"industry\":\"白酒\"}",
    )


class MonitorRuleUpsertInput(BaseModel):
    rule_id: str | None = Field(
        default=None,
        description="规则ID。提供则部分更新现有规则（未提供的字段保留原值），不提供则创建新规则",
    )
    rule_type: str | None = Field(
        default=None,
        description=(
            "规则类型（创建时必填）：price_change_pct_gt(涨跌幅超阈值%) / volume_spike(放量) / "
            "intel_keyword_match(情报关键词) / ma_crossover(均线交叉) / single_position_weight_gt(单仓超限%) / "
            "sector_correlation(板块联动) / data_provider_degraded(数据源降级) / combined_condition(组合条件)"
        ),
    )
    symbol: str | None = Field(default=None, description="股票代码，如 AAPL、600519（组合/持仓类规则可不填）")
    threshold: float | None = Field(default=None, description="阈值，如涨跌幅 5 表示 5%")
    keyword: str | None = Field(default=None, description="关键词（intel_keyword_match 用）")
    severity: str | None = Field(default=None, description="严重级别：low/medium/high")
    enabled: bool | None = Field(default=None, description="是否启用")
    cooldown_seconds: int | None = Field(default=None, description="触发冷却秒数（默认走风险策略配置）")
    title: str | None = Field(default=None, description="规则标题（可选，展示用）")


class MonitorRuleDeleteInput(BaseModel):
    rule_id: str = Field(description="要删除的规则ID")


class CapitalTierPatchInput(BaseModel):
    max_nav: float | None = Field(default=None, description="该档 NAV 上限（不含）；不传保留")
    single_position_max_weight_pct: float | None = Field(default=None, description="单票上限 %")
    single_position_warning_weight_pct: float | None = Field(default=None, description="单票预警 %")
    sector_max_weight_pct: float | None = Field(default=None, description="行业上限 %")
    min_holdings_count: int | None = Field(default=None, description="最少持仓只数")


class RiskPolicyUpdateInput(BaseModel):
    policy_id: str | None = Field(
        default=None,
        description="要修改的策略 ID；不传则修改当前生效策略（通常是 default-conservative）",
    )
    name: str | None = Field(default=None, description="策略名称")
    description: str | None = Field(default=None, description="策略描述")
    single_position_max_weight_pct: float | None = Field(
        default=None, description="≥10万档单票上限 %（基线字段）"
    )
    single_position_warning_weight_pct: float | None = Field(
        default=None, description="≥10万档单票预警 %"
    )
    sector_max_weight_pct: float | None = Field(default=None, description="≥10万档行业上限 %")
    min_holdings_count: int | None = Field(default=None, description="≥10万档最少持仓只数")
    etf_max_weight_pct: float | None = Field(default=None, description="ETF 独立仓位上限 %")
    single_position_max_loss_pct_of_nav: float | None = Field(
        default=None, description="单票浮亏占 NAV 上限 %"
    )
    draft_valid_hours: int | None = Field(default=None, description="调仓草案有效小时数")
    rebalance_min_delta_pct: float | None = Field(default=None, description="最小调仓变动 %")
    monitor_default_cooldown_seconds: int | None = Field(
        default=None, description="盯盘规则默认冷却秒数"
    )
    capital_tiers: list[CapitalTierPatchInput] | None = Field(
        default=None,
        description="完整替换资金分层表（按 max_nav 升序）；不传则保留原分层",
    )
    activate: bool = Field(default=False, description="更新后是否设为当前生效策略")


class RiskPolicyCreateInput(BaseModel):
    name: str = Field(description="新策略名称，如「均衡型」")
    description: str | None = Field(default="", description="策略描述")
    policy_id: str | None = Field(default=None, description="可选自定义 ID；默认由名称生成")
    single_position_max_weight_pct: float | None = Field(default=None, description="≥10万档单票上限 %")
    single_position_warning_weight_pct: float | None = Field(default=None, description="≥10万档预警 %")
    sector_max_weight_pct: float | None = Field(default=None, description="≥10万档行业上限 %")
    min_holdings_count: int | None = Field(default=None, description="≥10万档最少持仓")
    etf_max_weight_pct: float | None = Field(default=None, description="ETF 上限 %")
    single_position_max_loss_pct_of_nav: float | None = Field(default=None, description="单票最大亏损 %NAV")
    draft_valid_hours: int | None = Field(default=None, description="草案有效小时")
    rebalance_min_delta_pct: float | None = Field(default=None, description="最小调仓 %")
    monitor_default_cooldown_seconds: int | None = Field(default=None, description="盯盘冷却秒")
    capital_tiers: list[CapitalTierPatchInput] | None = Field(
        default=None, description="资金分层；不传则用出厂默认三档"
    )
    activate: bool = Field(default=False, description="创建后是否立即设为生效策略")


class RiskPolicyActivateInput(BaseModel):
    policy_id: str = Field(description="要激活的风险策略 ID")


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
    detail: Literal["summary", "full"] = Field(
        default="summary",
        description="summary（默认）=指标/周期/标的等摘要；full=含 signals/candidate_actions 等全量（很占上下文）",
    )
    fields: list[str] | None = Field(
        default=None,
        description="挑选字段；默认 summary 档为 run_id/strategy_*/period/universe/metrics/…",
    )


class ReportGenerateInput(BaseModel):
    report_type: str = Field(description="报告类型（stock_research/monitor_review/strategy_backtest/paper_portfolio_review/ops_briefing）")
    source_type: str = Field(description="来源类型（stock/monitor_event/backtest_run/paper_portfolio_snapshot/scheduled_task）")
    source_id: str = Field(description="来源ID 或 symbol")
    template_id: str | None = Field(default=None, description="报告模板ID")
    title: str | None = Field(default=None, description="报告标题")
    options: dict[str, Any] | None = Field(default=None, description="额外选项")
    detail: Literal["summary", "full"] = Field(
        default="summary",
        description="summary（默认）=元数据+路径，不含正文；full=含完整 content（很长）",
    )
    fields: list[str] | None = Field(default=None, description="挑选返回字段")


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
get_stock_financial = _tool(
    "get_stock_financial",
    "获取指定股票的财务报表数据（营收、净利润、总资产、总负债等），用于估值与财务健康分析。",
    StockInput, AuthorityLevel.A2,
)
get_daily_history = _tool(
    "get_daily_history",
    "获取指定股票的历史K线。默认返回区间统计（涨跌幅/最高最低/均量/波动率/最大回撤）加最近5根，"
    "足够判断走势；需要逐日数据再用 detail='ohlc' 配 fields/limit，或 detail='full' 取全量。",
    HistoryInput, AuthorityLevel.A2,
)
search_stock_intel = _tool(
    "search_stock_intel",
    "搜索指定股票的相关情报资讯，如新闻、公告、研报摘要。默认返回最近8条的标题/来源/时间/链接，"
    "可用 fields 指定字段、limit 调整条数。",
    IntelInput, AuthorityLevel.A2,
)
add_watchlist_item = _tool(
    "add_watchlist_item",
    "添加股票到自选列表。需要提供股票代码，股票名称和分组可选。",
    WatchlistAddInput, AuthorityLevel.A2,
)
list_watchlist = _tool(
    "list_watchlist",
    "列出当前自选股。清空自选前应先调用本工具确认列表；可用 group_name / monitored_only / limit 筛选。",
    WatchlistListInput, AuthorityLevel.A2,
)
remove_watchlist_item = _tool(
    "remove_watchlist_item",
    "删除自选：传 symbol 删单票；clear_all=true 清空全部自选。用户说「清空自选」时用 clear_all，不要瞎猜代码。",
    WatchlistRemoveInput, AuthorityLevel.A2,
)
get_industry_context = _tool(
    "get_industry_context",
    "获取行业竞争格局：行业行情快照、个股在行业内的市值排名与 PE/PB/涨幅分位、Top10 成分股对比。仅覆盖 A 股。",
    IndustryContextInput, AuthorityLevel.A2,
)
list_data_sources = _tool(
    "list_data_sources",
    "列出可用数据源目录（能力、鉴权方式说明、是否已配置凭证、健康态）。不含密钥。"
    "快捷工具 degraded 或需跨源时先调本工具，再 describe/invoke。",
    ListDataSourcesInput, AuthorityLevel.A2,
)
describe_data_capability = _tool(
    "describe_data_capability",
    "查看某数据源或某能力的参数 schema、返回摘要与局限。provider 与 capability 可单独或组合传入。",
    DescribeDataCapabilityInput, AuthorityLevel.A2,
)
invoke_data_capability = _tool(
    "invoke_data_capability",
    "按指定数据源直接调用命名能力（Mode A）。凭证由服务端注入，勿在对话中粘贴 Token。"
    "例：invoke_data_capability(provider='tonghuashun', capability='industry_boards')。",
    InvokeDataCapabilityInput, AuthorityLevel.A2,
)
get_market_structure = _tool(
    "get_market_structure",
    "获取个股市场结构：本地技术量价（均线/RSI/MACD/ATR/支撑阻力）、估值与流动性快照；A 股另含东财筹码（获利/套牢）与资金流向。港美股无筹码数字。看 freshness.stale / expected_as_of；stale 时不要把旧 K 线当天的量价。",
    StockInput, AuthorityLevel.A2,
)
refresh_market_data = _tool(
    "refresh_market_data",
    "绕过行情与日K缓存，补拉该股最新报价、官方日K，并重试快照/筹码/资金流。同一标的在设置中的「同股补拉冷却」内只打穿一次。"
    "用户明确要求刷新，或 get_market_structure/get_daily_history 的 stale=true 且问题依赖现价或今日量价时调用；不要每次 get_stock_context 都调用。",
    StockInput, AuthorityLevel.A2,
)
get_monitor_events = _tool(
    "get_monitor_events",
    "获取盯盘监控事件列表。默认精简字段；需要归因时设 include_explanation=true。",
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
upsert_monitor_rule = _tool(
    "upsert_monitor_rule",
    "创建或修改盯盘监控规则（涨跌幅/放量/关键词/均线交叉/仓位超限等）。带 rule_id 为部分更新，否则新建。",
    MonitorRuleUpsertInput, AuthorityLevel.A3,
)
delete_monitor_rule = _tool(
    "delete_monitor_rule",
    "删除指定的盯盘监控规则。",
    MonitorRuleDeleteInput, AuthorityLevel.A3,
)
list_strategies = _tool(
    "list_strategies",
    "获取所有策略库中的策略列表。",
    StrategyListInput, AuthorityLevel.A2,
)
get_backtest_result = _tool(
    "get_backtest_result",
    "获取回测结果。默认 summary（指标/周期/标的）；需要 signals 等全量时用 detail='full'。",
    BacktestGetInput, AuthorityLevel.A2,
)
list_report_templates = _tool(
    "list_report_templates",
    "获取所有可用的报告模板列表。",
    EmptyInput, AuthorityLevel.A2,
)
generate_report = _tool(
    "generate_report",
    "生成分析报告。默认只返回元数据+路径（不含正文）；需要全文时用 detail='full'。",
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
remove_holding = _tool(
    "remove_holding",
    "删除持仓：传 symbol 删单票；clear_all=true 清空全部。仅改本系统数据，不涉及真实交易。用户说「清空持仓/清仓」时用本工具，不要用 quantity=0 的 upsert。",
    HoldingRemoveInput, AuthorityLevel.A3,
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
update_risk_policy = _tool(
    "update_risk_policy",
    "部分更新风险策略阈值（资金分层、单票/行业上限、ETF 上限、单票最大亏损等）。"
    "未传字段保留原值；不传 policy_id 则改当前生效策略。仅改本系统风控规则，不涉及真实交易。",
    RiskPolicyUpdateInput, AuthorityLevel.A3,
)
create_risk_policy = _tool(
    "create_risk_policy",
    "新建一条风险策略（默认不激活）。可传 activate=true 创建后立即生效。"
    "未传的阈值字段用出厂默认（含资金分层与 ETF 上限）。",
    RiskPolicyCreateInput, AuthorityLevel.A3,
)
activate_risk_policy = _tool(
    "activate_risk_policy",
    "切换当前生效的风险策略（同时仅一条生效）。",
    RiskPolicyActivateInput, AuthorityLevel.A3,
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

# DeerFlow-native skill / MCP (enable/disable & server config; mid-chat)
class SkillListInput(BaseModel):
    enabled_only: bool = Field(default=False, description="为 True 时只返回已启用技能")


class SkillUpdateInput(BaseModel):
    name: str = Field(description="技能名称（DeerFlow skill name）")
    enabled: bool = Field(description="是否启用该技能")


class McpUpsertInput(BaseModel):
    name: str = Field(description="MCP 服务器名称")
    enabled: bool | None = Field(default=None, description="是否启用")
    type: str | None = Field(default=None, description="stdio / sse / http 等")
    command: str | None = Field(default=None, description="stdio 启动命令")
    args: list[str] | None = Field(default=None, description="stdio 参数")
    url: str | None = Field(default=None, description="sse/http 服务地址")
    env: dict[str, str] | None = Field(default=None, description="环境变量（勿在回复中回显明文）")
    description: str | None = Field(default=None, description="可选说明")


class McpRemoveInput(BaseModel):
    name: str = Field(description="要删除的 MCP 服务器名称")


list_skills = _tool(
    "list_skills",
    "列出 DeerFlow 技能目录及启用状态（原生 list_skills）。用户要求查看/调整技能时先调用。",
    SkillListInput, AuthorityLevel.A2,
)
update_skill = _tool(
    "update_skill",
    "启用或禁用指定技能（DeerFlow 原生 update_skill，写入 extensions / 用户技能状态，随后重建 runtime）。"
    "不要用 update_agent 改 skills。",
    SkillUpdateInput, AuthorityLevel.A3,
)
list_mcp_servers = _tool(
    "list_mcp_servers",
    "列出已配置的 MCP 服务器（原生 get_mcp_config；env 密钥已脱敏为 ***）。",
    EmptyInput, AuthorityLevel.A2,
)
upsert_mcp_server = _tool(
    "upsert_mcp_server",
    "新增或更新一个 MCP 服务器配置（读现有配置后合并写回，原生 update_mcp_config）。"
    "勿在对话中回显 env 明文。",
    McpUpsertInput, AuthorityLevel.A3,
)
remove_mcp_server = _tool(
    "remove_mcp_server",
    "从 extensions 配置中删除指定 MCP 服务器（原生 update_mcp_config）。",
    McpRemoveInput, AuthorityLevel.A3,
)

# A4: Planner tools
generate_draft_order = _tool(
    "generate_draft_order",
    "生成拟单草案，指定股票代码和目标权重，返回草案详情。",
    DraftOrderInput, AuthorityLevel.A4,
)
list_rebalance_drafts = _tool(
    "list_rebalance_drafts",
    "获取拟单草案列表。默认精简字段；可用 fields/limit 控制返回体量。",
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

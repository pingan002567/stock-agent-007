from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional

from backend.execution_guard import canonical_execution_guard
from pydantic import BaseModel, Field, model_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "json"):
        return json.loads(value.json())
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


class AuthorityLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"


class RebalanceDraftStatus(str, Enum):
    PENDING_USER_CONFIRMATION = "pending_user_confirmation"
    CONFIRMED_NO_EXECUTION = "confirmed_no_execution"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PreTradeReviewStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    BLOCKED = "blocked"


class PaperOrderStatus(str, Enum):
    PAPER_SUBMITTED = "paper_submitted"
    PAPER_FILLED = "paper_filled"
    PAPER_CANCELLED = "paper_cancelled"
    PAPER_REJECTED = "paper_rejected"


class ReviewInboxStateStatus(str, Enum):
    OPEN = "open"
    DISMISSED = "dismissed"
    DONE = "done"


class PriceSnapshot(BaseModel):
    last: float
    change_pct: float
    updated_at: str
    source: str = "mock_adapter"
    degraded: bool = False
    degraded_reason: Optional[str] = None
    coverage: Optional[Dict[str, Any]] = None


class StockRelation(BaseModel):
    in_watchlist: bool = False
    in_holdings: bool = False
    monitored: bool = False


class HoldingInfo(BaseModel):
    weight_pct: float = 0
    quantity: float = 0
    market_value: float = 0
    cost: Optional[float] = None
    pnl_pct: Optional[float] = None


class AIState(BaseModel):
    score: int
    risk_label: str
    stance: str
    confidence: str


class LatestReport(BaseModel):
    report_id: Optional[str] = None
    generated_at: Optional[str] = None


class StockContext(BaseModel):
    symbol: str
    name: str
    market: str
    industry: str
    sector: str
    price: PriceSnapshot
    relation: StockRelation
    holding: HoldingInfo = Field(default_factory=HoldingInfo)
    ai_state: AIState
    latest_report: LatestReport = Field(default_factory=LatestReport)


class EventContext(BaseModel):
    event_id: str
    source: str
    symbol: str
    title: str
    severity: str
    triggered_at: str
    trigger_rule: str
    rule_id: Optional[str] = None
    rule_type: Optional[str] = None
    dedupe_key: Optional[str] = None
    cooldown_until: Optional[str] = None
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_actions: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class DecisionContext(BaseModel):
    decision_id: str
    subject: Dict[str, str]
    skill: str
    conclusion: str
    confidence: str
    reasons: List[str]
    counter_reasons: List[str]
    evidence_refs: List[str]
    valid_until: str
    authority_level: AuthorityLevel
    output: Dict[str, Any]


class SSEEvent(BaseModel):
    run_id: str
    task_id: str
    type: str
    payload: Dict[str, Any]
    created_at: str = Field(default_factory=now_iso)


class AgentTask(BaseModel):
    task_id: str
    title: str
    source: str
    progress: int
    status: str
    current_step: str
    run_id: Optional[str] = None
    skill_trace: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ToolExecution(BaseModel):
    execution_id: str
    tool: str
    domain: str
    status: str
    authority_level: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    call_id: Optional[str] = None
    source_mode: str = "unknown"
    evidence_refs: List[str] = Field(default_factory=list)
    result_summary: str = ""
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class RuntimeConfig(BaseModel):
    runtime_mode: str = "embedded"
    config_path: Optional[str] = None
    model_name: Optional[str] = None
    thinking_enabled: bool = True
    request_timeout_seconds: int = 60
    stream_timeout_seconds: int = 180
    fallback_policy: str = "direct_on_failure"
    enable_usage_tracking: bool = True
    enable_provider_logging: bool = True
    enable_copilot_logging: bool = True


class ProviderCallLog(BaseModel):
    call_id: str
    capability: str
    market: Optional[str] = None
    symbol: Optional[str] = None
    provider: str
    fallback_provider: str
    status: str
    degraded_reason: Optional[str] = None
    duration_ms: float = 0.0
    created_at: str = Field(default_factory=now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


class CopilotRunLog(BaseModel):
    run_id: str
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    mode: str = "stub"
    active_client: str = "stub"
    model_name: Optional[str] = None
    status: str = "running"
    error_category: Optional[str] = None
    runtime_error: Optional[str] = None
    tool_call_count: int = 0
    usage_input_tokens: Optional[int] = None
    usage_output_tokens: Optional[int] = None
    cost: Optional[float] = None
    latency_ms: Optional[float] = None
    started_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


class RuntimeMetricSnapshot(BaseModel):
    snapshot_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class AIRunEvaluationCase(BaseModel):
    case_id: str
    message: str
    page: str = "overview"
    symbol: Optional[str] = None
    authority_level: AuthorityLevel = AuthorityLevel.A4
    expected_skills: List[str] = Field(default_factory=list)
    expected_tools: List[str] = Field(default_factory=list)
    min_final_keys: List[str] = Field(
        default_factory=lambda: ["conclusion", "confidence", "disclaimer"]
    )
    allow_degraded_data: bool = True


class AIRunEvaluationResult(BaseModel):
    case_id: str
    passed: bool
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    final_type: Optional[str] = None
    actual_skills: List[str] = Field(default_factory=list)
    actual_tools: List[str] = Field(default_factory=list)
    missing_final_keys: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class RiskPolicyRules(BaseModel):
    single_position_max_weight_pct: float = 15
    single_position_warning_weight_pct: float = 12
    sector_max_weight_pct: float = 35
    draft_valid_hours: int = 24
    rebalance_min_delta_pct: float = 2.0
    monitor_default_cooldown_seconds: int = 3600

    @model_validator(mode="after")
    def validate_thresholds(self) -> "RiskPolicyRules":
        if (
            not 0
            < self.single_position_warning_weight_pct
            <= self.single_position_max_weight_pct
            <= 100
        ):
            raise ValueError(
                "single_position_warning_weight_pct must satisfy 0 < warning <= max <= 100"
            )
        if not 0 < self.sector_max_weight_pct <= 100:
            raise ValueError(
                "sector_max_weight_pct must satisfy 0 < sector_max_weight_pct <= 100"
            )
        if self.draft_valid_hours <= 0:
            raise ValueError("draft_valid_hours must be greater than 0")
        if self.rebalance_min_delta_pct < 0:
            raise ValueError(
                "rebalance_min_delta_pct must be greater than or equal to 0"
            )
        if self.monitor_default_cooldown_seconds < 0:
            raise ValueError(
                "monitor_default_cooldown_seconds must be greater than or equal to 0"
            )
        return self


class RiskPolicyRef(BaseModel):
    policy_id: str
    name: str
    version: int = 1
    updated_at: str


class RiskPolicy(BaseModel):
    policy_id: Optional[str] = None
    name: str
    description: str = ""
    is_active: bool = False
    is_default: bool = False
    rules: RiskPolicyRules = Field(default_factory=RiskPolicyRules)
    version: int = 1
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class StrategySpec(BaseModel):
    strategy_id: Optional[str] = None
    name: str
    description: str = ""
    strategy_type: str = "concentration_control"
    enabled: bool = True
    risk_level: str = "medium"
    universe: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class BacktestMetrics(BaseModel):
    """Enhanced backtest metrics with standard financial indicators."""
    # 收益指标
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None
    
    # 风险指标
    max_drawdown_pct: float = 0.0
    volatility_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    # 交易统计
    win_rate: float = 0.0
    
    # 回测配置
    sample_size: int = 0
    lookback_days: int = 30


class BacktestRun(BaseModel):
    run_id: str
    strategy_id: str
    strategy_name: str
    strategy_type: str
    strategy_snapshot: Dict[str, Any]
    period: Dict[str, Any] = Field(default_factory=dict)
    universe: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    signals: List[Dict[str, Any]] = Field(default_factory=list)
    risk_summary: Dict[str, Any] = Field(default_factory=dict)
    candidate_actions: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    risk_policy_ref: Optional[RiskPolicyRef] = None
    execution_guard: Dict[str, Any] = Field(
        default_factory=lambda: {
            "research_only": True,
            "auto_trade": False,
            "place_real_order_enabled": False,
        }
    )
    degraded: bool = False
    degraded_reason: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class ReportTemplate(BaseModel):
    template_id: str
    report_type: str
    name: str
    summary: str = ""
    source_types: List[str] = Field(default_factory=list)
    sections: List[str] = Field(default_factory=list)
    visible: bool = True
    registry_source: str = "code"
    version: str = "v0.12"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ReportGenerateRequest(BaseModel):
    report_type: str
    source_type: str
    source_id: str
    template_id: Optional[str] = None
    title: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class ReportQualityCheck(BaseModel):
    check_id: str
    report_id: str
    template_id: Optional[str] = None
    report_type: str
    source_type: str
    source_id: str
    status: str
    summary: str
    score: int = 0
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    degraded: bool = False
    created_at: str = Field(default_factory=now_iso)


class Report(BaseModel):
    report_id: str
    title: str
    symbol: str = ""
    report_type: str
    conclusion: str
    evidence_count: int
    content: str
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    source_type: str = "stock"
    source_id: str = ""
    source_label: Optional[str] = None
    quality_status: Optional[str] = None
    quality_summary: Optional[str] = None
    latest_quality_check_id: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    valid_until: Optional[str] = None
    disclaimer: str = "仅供研究，不构成投资建议。"
    degraded: bool = False
    degraded_reason: Optional[str] = None
    candidate_actions: List[Dict[str, Any]] = Field(default_factory=list)
    execution_guard: Dict[str, Any] = Field(
        default_factory=lambda: {
            "research_only": True,
            "auto_trade": False,
            "place_real_order_enabled": False,
        }
    )
    risk_policy_ref: Optional[RiskPolicyRef] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    markdown_path: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class AuditLog(BaseModel):
    audit_id: str
    action: str
    detail: str
    authority_level: AuthorityLevel = AuthorityLevel.A1
    created_at: str = Field(default_factory=now_iso)


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    group: str = "观察池"
    tags: List[str] = Field(default_factory=list)
    monitored: bool = False


class HoldingPosition(BaseModel):
    symbol: str
    name: str
    quantity: float
    market_value: float
    weight_pct: float
    cost: Optional[float] = None
    pnl_pct: Optional[float] = None


class RebalanceDraftRequest(BaseModel):
    symbol: str
    target_weight_pct: float


class RebalanceDraftCreateRequest(BaseModel):
    symbol: str
    target_weight_pct: float


class RebalanceDraftDecisionNoteRequest(BaseModel):
    note: str = ""


class PreTradeReviewCreateRequest(BaseModel):
    draft_id: str


class PaperOrderCreateRequest(BaseModel):
    review_id: str


class PaperOrderCancelRequest(BaseModel):
    note: str = ""


class RebalanceDraft(BaseModel):
    draft_id: str
    decision_id: str
    symbol: str
    name: str
    action: str
    current_weight_pct: float
    target_weight_pct: float
    delta_weight_pct: float
    status: RebalanceDraftStatus = RebalanceDraftStatus.PENDING_USER_CONFIRMATION
    authority_level: AuthorityLevel = AuthorityLevel.A4
    confidence: str = "medium"
    conclusion: str
    reasons: List[str] = Field(default_factory=list)
    counter_reasons: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    auto_trade: bool = False
    valid_until: str
    validity_source: str = "risk_policy.rules.draft_valid_hours"
    risk_policy_ref: Optional[RiskPolicyRef] = None
    note: Optional[str] = None
    source_mode: str = "http"
    output: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    confirmed_at: Optional[str] = None
    rejected_at: Optional[str] = None
    expired_at: Optional[str] = None


class PreTradeReview(BaseModel):
    review_id: str
    source_draft_id: str
    status: PreTradeReviewStatus = PreTradeReviewStatus.BLOCKED
    symbol: str
    side: str
    current_weight_pct: float
    target_weight_pct: float
    delta_weight_pct: float
    draft_status_at_review: str
    risk_policy_ref: Optional[RiskPolicyRef] = None
    risk_policy_rules_snapshot: Dict[str, Any] = Field(default_factory=dict)
    quote_snapshot: Dict[str, Any] = Field(default_factory=dict)
    portfolio_total_value: float = 0
    checklist: List[Dict[str, Any]] = Field(default_factory=list)
    blocker_codes: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    execution_guard: Dict[str, Any] = Field(default_factory=canonical_execution_guard)
    degraded: bool = False
    degraded_reason: Optional[str] = None
    source_mode: str = "http"
    created_at: str = Field(default_factory=now_iso)


class PaperOrder(BaseModel):
    order_id: str
    review_id: str
    source_draft_id: str
    status: PaperOrderStatus
    symbol: str
    side: str
    target_weight_pct: float
    delta_weight_pct: float
    paper_price: float
    paper_price_source: str
    paper_price_updated_at: str
    paper_quantity_estimate: float
    paper_notional_estimate: float
    quote_degraded: bool = False
    quote_degraded_reason: Optional[str] = None
    risk_policy_ref: Optional[RiskPolicyRef] = None
    execution_guard: Dict[str, Any] = Field(default_factory=canonical_execution_guard)
    evidence_refs: List[str] = Field(default_factory=list)
    source_mode: str = "http"
    created_at: str = Field(default_factory=now_iso)
    filled_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    rejected_at: Optional[str] = None
    note: Optional[str] = None


class PaperPortfolioBaselinePosition(BaseModel):
    symbol: str
    name: str
    quantity: float
    baseline_price: float
    baseline_market_value: float
    baseline_cost_basis: float


class PaperPortfolioBaseline(BaseModel):
    baseline_id: str
    created_at: str = Field(default_factory=now_iso)
    source: str = "holding_position"
    initial_nav: float = 0
    initial_cash: float = 0
    positions: List[PaperPortfolioBaselinePosition] = Field(default_factory=list)


class PaperPortfolioWarning(BaseModel):
    code: str
    message: str
    symbol: Optional[str] = None
    order_id: Optional[str] = None


class PaperPortfolioPosition(BaseModel):
    symbol: str
    name: str
    quantity: float
    cost_basis: float
    avg_cost: float
    baseline_quantity: float
    baseline_price: float
    baseline_market_value: float
    baseline_cost_basis: float
    market_value: float
    pnl: float
    weight_pct: float
    quote: Dict[str, Any] = Field(default_factory=dict)
    last_order_risk_policy_ref: Optional[RiskPolicyRef] = None


class PaperPortfolioProjection(BaseModel):
    baseline_id: str
    as_of: str = Field(default_factory=now_iso)
    degraded: bool = False
    source: str = "paper_portfolio_projection"
    initial_nav: float = 0
    initial_cash: float = 0
    market_value: float = 0
    cash_estimate: float = 0
    equity_estimate: float = 0
    pnl_estimate: float = 0
    order_count: int = 0
    warning_count: int = 0
    positions: List[PaperPortfolioPosition] = Field(default_factory=list)
    warnings: List[PaperPortfolioWarning] = Field(default_factory=list)
    quotes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    latest_risk_policy_ref: Optional[RiskPolicyRef] = None
    risk_policy_refs: List[RiskPolicyRef] = Field(default_factory=list)


class PaperPortfolioSnapshot(BaseModel):
    snapshot_id: str
    baseline_id: str
    as_of: str
    degraded: bool = False
    market_value: float = 0
    cash_estimate: float = 0
    equity_estimate: float = 0
    pnl_estimate: float = 0
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class DecisionJournalLinkSnapshotRequest(BaseModel):
    snapshot_id: Optional[str] = None


class DecisionJournalCloseRequest(BaseModel):
    close_note: str = ""


class DecisionJournalEntry(BaseModel):
    entry_id: str
    decision_id: str
    symbol: str
    status: str
    source_type: str
    draft_id: Optional[str] = None
    review_id: Optional[str] = None
    paper_order_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    report_id: Optional[str] = None
    closed_at: Optional[str] = None
    close_note: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ReviewInboxState(BaseModel):
    item_key: str
    status: ReviewInboxStateStatus = ReviewInboxStateStatus.OPEN
    snoozed_until: Optional[str] = None
    note: Optional[str] = None
    updated_at: str = Field(default_factory=now_iso)


class ReviewInboxItem(BaseModel):
    item_key: str
    item_type: str
    source_type: str
    source_id: str
    title: str
    summary: str
    priority: str
    severity: str
    status: ReviewInboxStateStatus = ReviewInboxStateStatus.OPEN
    snoozed_until: Optional[str] = None
    note: Optional[str] = None
    occurred_at: str
    updated_at: str
    evidence_refs: List[str] = Field(default_factory=list)
    draft_id: Optional[str] = None
    review_id: Optional[str] = None
    entry_id: Optional[str] = None
    event_id: Optional[str] = None
    report_id: Optional[str] = None
    snapshot_id: Optional[str] = None


class ReviewInboxSummary(BaseModel):
    open_count: int = 0
    high_count: int = 0
    overdue_count: int = 0
    snoozed_count: int = 0


class ReviewInboxActionRequest(BaseModel):
    note: str = ""


class ReviewInboxSnoozeRequest(BaseModel):
    snoozed_until: str
    note: str = ""


class CopilotSession(BaseModel):
    session_id: str
    title: str
    status: str = "active"
    current_page: str = "overview"
    anchor_symbol: Optional[str] = None
    authority_level: AuthorityLevel = AuthorityLevel.A4
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    last_message_at: Optional[str] = None


class CopilotSessionCreateRequest(BaseModel):
    title: Optional[str] = None
    current_page: str = "overview"
    anchor_symbol: Optional[str] = None
    authority_level: AuthorityLevel = AuthorityLevel.A4


class CopilotMessage(BaseModel):
    message_id: str
    session_id: str
    role: str
    kind: str
    text: str = ""
    page: Optional[str] = None
    symbol: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    client_message_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


class CopilotRequest(BaseModel):
    message: str
    page: str = "overview"
    symbol: Optional[str] = None
    authority_level: AuthorityLevel = AuthorityLevel.A4
    session_id: Optional[str] = None
    client_message_id: Optional[str] = None


class CopilotSessionUpdateRequest(BaseModel):
    title: str

    @model_validator(mode="after")
    def validate_title(self) -> "CopilotSessionUpdateRequest":
        if not self.title or not self.title.strip():
            raise ValueError("title must not be empty")
        return self


class CopilotSessionMessageRequest(BaseModel):
    message: str
    page: Optional[str] = None
    symbol: Optional[str] = None
    authority_level: Optional[AuthorityLevel] = None
    client_message_id: Optional[str] = None


class CopilotRun(BaseModel):
    run_id: str
    task_id: str
    intent: str
    skill: str
    skills: List[str] = Field(default_factory=list)
    status: str = "running"
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class MonitorRule(BaseModel):
    rule_id: str
    rule_type: str
    symbol: Optional[str] = None
    severity: str = "medium"
    enabled: bool = True
    threshold: Optional[float] = None
    keyword: Optional[str] = None
    cooldown_seconds: int = 3600
    title: Optional[str] = None
    trigger_rule: Optional[str] = None
    source: str = "user"
    rule_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class MonitorStatus(BaseModel):
    status: str = "paused"
    auto_start: bool = False
    interval_seconds: int = 60
    last_checked_at: Optional[str] = None
    last_matched_at: Optional[str] = None
    last_error: Optional[str] = None
    updated_at: str = Field(default_factory=now_iso)


class StockMaster(BaseModel):
    symbol: str
    name: str
    market: str
    industry: str = ""
    sector: str = ""
    aliases: List[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class StockDaily(BaseModel):
    symbol: str
    trade_date: str
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    source: str = ""
    created_at: str = Field(default_factory=now_iso)


class StockQuote(BaseModel):
    symbol: str
    last: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    source: str = ""
    provider: str = ""
    hit_count: int = 0
    updated_at: str = Field(default_factory=now_iso)


class StockFinancial(BaseModel):
    symbol: str
    report_date: str
    report_type: str = "annual"
    revenue: float = 0.0
    profit: float = 0.0
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


# ── World Cup Prediction Models ─────────────────────────────────────────

class WorldCupTeam(BaseModel):
    team_id: str
    name: str
    name_en: str = ""
    group: str = ""
    fifa_ranking: int = 0
    elo_rating: int = 0
    flag_emoji: str = ""
    created_at: str = Field(default_factory=now_iso)


class WorldCupMatch(BaseModel):
    match_id: str
    stage: str = "group"
    group: Optional[str] = None
    home_team_id: str
    away_team_id: str
    home_team_name: str = ""
    away_team_name: str = ""
    home_flag: str = ""
    away_flag: str = ""
    match_time: str = ""
    venue: str = ""
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    status: str = "upcoming"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class WorldCupOdds(BaseModel):
    odds_id: str
    match_id: str
    bookmaker: str
    home_win: float = 0.0
    draw: float = 0.0
    away_win: float = 0.0
    over_2_5: float = 0.0
    under_2_5: float = 0.0
    timestamp: str = Field(default_factory=now_iso)


class WorldCupPrediction(BaseModel):
    prediction_id: str
    match_id: str
    predicted_home_score: int = 0
    predicted_away_score: int = 0
    confidence: float = 0.5
    created_at: str = Field(default_factory=now_iso)


class WorldCupBet(BaseModel):
    bet_id: str
    match_id: str
    match_name: str = ""
    bet_type: str = "home"
    odds: float = 0.0
    stake: float = 0.0
    probability: float = 0.0
    expected_value: float = 0.0
    status: str = "pending"
    profit: Optional[float] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

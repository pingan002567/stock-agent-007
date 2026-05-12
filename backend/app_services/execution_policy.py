from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    AUTO_SAFE = "auto_safe"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ExecutionDecision:
    mode: ExecutionMode
    reason: str
    next_action: str | None = None


class ExecutionPolicy:
    AUTO_SAFE_TOOLS = {
        "get_stock_context",
        "get_daily_history",
        "search_stock_intel",
        "get_portfolio_snapshot",
        "get_active_risk_policy",
        "list_risk_policies",
        "evaluate_policy_risk",
        "analyze_portfolio_risk",
        "get_monitor_events",
        "get_monitor_rules",
        "evaluate_monitor_rules",
        "generate_draft_order",
        "create_pre_trade_review",
        "list_strategies",
        "run_strategy_backtest",
        "get_backtest_result",
        "list_report_templates",
        "generate_report",
        "get_report_quality",
        "list_rebalance_drafts",
        "get_rebalance_draft",
        "list_pre_trade_reviews",
        "list_paper_orders",
        "get_paper_portfolio",
        "analyze_paper_performance",
        "create_paper_portfolio_snapshot",
        "list_decision_journal",
        "get_decision_journal_entry",
        "summarize_decision_outcomes",
        "list_review_inbox",
        "summarize_review_inbox",
        "confirm_rebalance_draft",
        "reject_rebalance_draft",
        "add_watchlist_item",
        "remove_watchlist_item",
        "upsert_holding",
        "dismiss_inbox_item",
        "snooze_inbox_item",
        "mark_inbox_item_done",
    }
    NEEDS_CONFIRMATION_ACTIONS = {
        "draft_confirm",
        "draft_reject",
        "create_paper_order",
        "cancel_paper_order",
        "decision_journal_close",
        "decision_journal_link_snapshot",
    }
    BLOCKED_ACTIONS = {"place_real_order", "TeamRun"}

    def __init__(self, default_mode: ExecutionMode = ExecutionMode.AUTO_SAFE) -> None:
        self.default_mode = default_mode

    def decide(self, action_name: str) -> ExecutionDecision:
        if action_name in self.BLOCKED_ACTIONS:
            return ExecutionDecision(
                mode=ExecutionMode.BLOCKED,
                reason="该动作超出 V1 产品边界，真实交易与 TeamRun 均保持关闭。",
                next_action="使用页面显式 HTTP/UI 能力，且不要启用真实交易。",
            )
        if action_name in self.NEEDS_CONFIRMATION_ACTIONS:
            return ExecutionDecision(
                mode=ExecutionMode.NEEDS_CONFIRMATION,
                reason="该动作会改变草案、审查、paper sandbox 或待办状态，必须由用户显式确认。",
                next_action="在对应页面使用显式按钮完成该动作。",
            )
        if action_name in self.AUTO_SAFE_TOOLS:
            return ExecutionDecision(
                mode=ExecutionMode.AUTO_SAFE,
                reason="该动作属于只读研究或低风险自动产物，允许自动执行并写审计记录。",
            )
        return ExecutionDecision(mode=self.default_mode, reason="使用默认执行模式。")

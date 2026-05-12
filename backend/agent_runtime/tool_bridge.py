from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict

from backend.app_services.audit_service import AuditService
from backend.app_services.context_builder import ContextBuilder
from backend.app_services.decision_journal_service import DecisionJournalService
from backend.app_services.execution_policy import ExecutionMode, ExecutionPolicy
from backend.app_services.monitor_service import MonitorService
from backend.app_services.paper_portfolio_service import PaperPortfolioService
from backend.app_services.paper_trading_service import PaperTradingService
from backend.app_services.permission_guard import PermissionDenied, PermissionGuard
from backend.app_services.pre_trade_review_service import PreTradeReviewService
from backend.app_services.rebalance_draft_service import RebalanceDraftService
from backend.app_services.report_service import ReportService
from backend.app_services.review_inbox_service import ReviewInboxService
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.app_services.strategy_service import StrategyService
from backend.app_services.tool_execution_service import ToolExecutionService
from backend.app_services.worldcup_service import WorldCupService
from backend.persistence.file_store import FileStore
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AuthorityLevel, HoldingPosition, RebalanceDraftDecisionNoteRequest, RebalanceDraftStatus, ReportGenerateRequest, model_to_dict
from backend.stock_domain.history_tools import get_daily_history
from backend.stock_domain.intel_tools import search_stock_intel
from backend.stock_domain.portfolio_tools import summarize_portfolio


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    required_authority: AuthorityLevel
    risk: str
    enabled: bool
    input_schema: dict[str, Any]
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_authority"] = self.required_authority.value
        data["status"] = "enabled" if self.enabled else "blocked"
        return data


class WorkbenchToolBridge:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        repo: WorkbenchRepository,
        monitor_service: MonitorService | None = None,
        risk_policy_service: RiskPolicyService | None = None,
        strategy_service: StrategyService | None = None,
        rebalance_draft_service: RebalanceDraftService | None = None,
        pre_trade_review_service: PreTradeReviewService | None = None,
        paper_trading_service: PaperTradingService | None = None,
        paper_portfolio_service: PaperPortfolioService | None = None,
        report_service: ReportService | None = None,
        decision_journal_service: DecisionJournalService | None = None,
        review_inbox_service: ReviewInboxService | None = None,
        worldcup_service: WorldCupService | None = None,
        permission_guard: PermissionGuard,
        tool_execution_service: ToolExecutionService | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.repo = repo
        self.risk_policy_service = risk_policy_service or RiskPolicyService(repo, AuditService(repo))
        self.monitor_service = monitor_service or MonitorService(
            repo=repo,
            context_builder=context_builder,
            audit_service=AuditService(repo),
            risk_policy_service=self.risk_policy_service,
        )
        self.strategy_service = strategy_service or StrategyService(repo, AuditService(repo), self.risk_policy_service)
        self.paper_portfolio_service = paper_portfolio_service or PaperPortfolioService(
            repo=repo,
            audit_service=AuditService(repo),
        )
        self.decision_journal_service = decision_journal_service or DecisionJournalService(
            repo=repo,
            audit_service=AuditService(repo),
            paper_portfolio_service=self.paper_portfolio_service,
        )
        self.rebalance_draft_service = rebalance_draft_service or RebalanceDraftService(
            repo=repo,
            context_builder=context_builder,
            audit_service=AuditService(repo),
            risk_policy_service=self.risk_policy_service,
            decision_journal_service=self.decision_journal_service,
        )
        self.pre_trade_review_service = pre_trade_review_service or PreTradeReviewService(
            repo=repo,
            audit_service=AuditService(repo),
            rebalance_draft_service=self.rebalance_draft_service,
            risk_policy_service=self.risk_policy_service,
            decision_journal_service=self.decision_journal_service,
        )
        self.paper_trading_service = paper_trading_service or PaperTradingService(
            repo=repo,
            audit_service=AuditService(repo),
            pre_trade_review_service=self.pre_trade_review_service,
            decision_journal_service=self.decision_journal_service,
        )
        self.report_service = report_service or ReportService(
            repo=repo,
            context_builder=context_builder,
            monitor_service=self.monitor_service,
            strategy_service=self.strategy_service,
            audit_service=AuditService(repo),
            file_store=FileStore("data/files"),
            decision_journal_service=self.decision_journal_service,
        )
        self.review_inbox_service = review_inbox_service or ReviewInboxService(
            repo=repo,
            rebalance_draft_service=self.rebalance_draft_service,
            pre_trade_review_service=self.pre_trade_review_service,
            monitor_service=self.monitor_service,
            paper_portfolio_service=self.paper_portfolio_service,
        )
        self.worldcup_service = worldcup_service or WorldCupService(repo=repo)
        self.permission_guard = permission_guard
        self.tool_execution_service = tool_execution_service
        self.execution_policy = execution_policy or ExecutionPolicy()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "get_stock_context": self._get_stock_context,
            "get_daily_history": self._get_daily_history,
            "search_stock_intel": self._search_stock_intel,
            "get_portfolio_snapshot": self._get_portfolio_snapshot,
            "get_active_risk_policy": self._get_active_risk_policy,
            "list_risk_policies": self._list_risk_policies,
            "evaluate_policy_risk": self._evaluate_policy_risk,
            "analyze_portfolio_risk": self._analyze_portfolio_risk,
            "get_monitor_events": self._get_monitor_events,
            "get_monitor_rules": self._get_monitor_rules,
            "evaluate_monitor_rules": self._evaluate_monitor_rules,
            "list_strategies": self._list_strategies,
            "run_strategy_backtest": self._run_strategy_backtest,
            "get_backtest_result": self._get_backtest_result,
            "list_report_templates": self._list_report_templates,
            "generate_report": self._generate_report,
            "get_report_quality": self._get_report_quality,
            "generate_draft_order": self._generate_draft_order,
            "list_rebalance_drafts": self._list_rebalance_drafts,
            "get_rebalance_draft": self._get_rebalance_draft,
            "create_pre_trade_review": self._create_pre_trade_review,
            "list_pre_trade_reviews": self._list_pre_trade_reviews,
            "list_paper_orders": self._list_paper_orders,
            "get_paper_portfolio": self._get_paper_portfolio,
            "analyze_paper_performance": self._analyze_paper_performance,
            "create_paper_portfolio_snapshot": self._create_paper_portfolio_snapshot,
            "list_decision_journal": self._list_decision_journal,
            "get_decision_journal_entry": self._get_decision_journal_entry,
            "summarize_decision_outcomes": self._summarize_decision_outcomes,
            "list_review_inbox": self._list_review_inbox,
            "summarize_review_inbox": self._summarize_review_inbox,
            "dismiss_inbox_item": self._dismiss_inbox_item,
            "snooze_inbox_item": self._snooze_inbox_item,
            "mark_inbox_item_done": self._mark_inbox_item_done,
            "confirm_rebalance_draft": self._confirm_draft,
            "reject_rebalance_draft": self._reject_draft,
            "add_watchlist_item": self._add_watchlist_item,
            "remove_watchlist_item": self._remove_watchlist_item,
            "upsert_holding": self._upsert_holding,
            "place_real_order": self._place_real_order,
            "get_worldcup_matches": self._get_worldcup_matches,
            "get_worldcup_odds": self._get_worldcup_odds,
            "get_worldcup_analysis": self._get_worldcup_analysis,
            "create_worldcup_prediction": self._create_worldcup_prediction,
            "create_worldcup_bet": self._create_worldcup_bet,
            "update_worldcup_bet": self._update_worldcup_bet,
            "delete_worldcup_bet": self._delete_worldcup_bet,
            "list_worldcup_bets": self._list_worldcup_bets,
        }
        self._specs = {
            "get_stock_context": ToolSpec(
                "get_stock_context",
                "stock",
                AuthorityLevel.A2,
                "low",
                True,
                {"symbol": "str"},
                ["stock_context", "provider_router"],
            ),
            "get_daily_history": ToolSpec(
                "get_daily_history",
                "market-data",
                AuthorityLevel.A2,
                "low",
                True,
                {"symbol": "str", "days": "int"},
                ["daily_history", "provider_router"],
            ),
            "search_stock_intel": ToolSpec(
                "search_stock_intel",
                "intel",
                AuthorityLevel.A2,
                "medium",
                True,
                {"symbol": "str", "query": "str"},
                ["stock_intel", "provider_router"],
            ),
            "get_portfolio_snapshot": ToolSpec(
                "get_portfolio_snapshot",
                "portfolio",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                ["holding_position", "local_sqlite"],
            ),
            "analyze_portfolio_risk": ToolSpec(
                "analyze_portfolio_risk",
                "risk",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                ["portfolio_risk", "risk_policy", "risk_rule:single_position_weight", "risk_rule:sector_weight"],
            ),
            "get_active_risk_policy": ToolSpec(
                "get_active_risk_policy",
                "risk",
                AuthorityLevel.A2,
                "low",
                True,
                {},
                ["risk_policy", "local_sqlite"],
            ),
            "list_risk_policies": ToolSpec(
                "list_risk_policies",
                "risk",
                AuthorityLevel.A2,
                "low",
                True,
                {},
                ["risk_policy", "local_sqlite"],
            ),
            "evaluate_policy_risk": ToolSpec(
                "evaluate_policy_risk",
                "risk",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                ["portfolio_risk", "risk_policy", "risk_rule:single_position_weight", "risk_rule:sector_weight"],
            ),
            "generate_draft_order": ToolSpec(
                "generate_draft_order",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"symbol": "str", "target_weight_pct": "float"},
                ["rebalance_draft", "holding_position", "stock_context", "draft_order_guard:auto_trade_false"],
            ),
            "list_rebalance_drafts": ToolSpec(
                "list_rebalance_drafts",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"symbol": "str?", "status": "str?", "limit": "int?"},
                ["rebalance_draft", "audit_log", "draft_order_guard:auto_trade_false"],
            ),
            "get_rebalance_draft": ToolSpec(
                "get_rebalance_draft",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"draft_id": "str"},
                ["rebalance_draft", "audit_log", "draft_order_guard:auto_trade_false"],
            ),
            "create_pre_trade_review": ToolSpec(
                "create_pre_trade_review",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"draft_id": "str"},
                ["pre_trade_review", "rebalance_draft", "risk_policy", "provider_router"],
            ),
            "confirm_rebalance_draft": ToolSpec(
                "confirm_rebalance_draft",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"draft_id": "str", "note": "str?"},
                ["rebalance_draft", "audit_log", "draft_order_guard:auto_trade_false"],
            ),
            "reject_rebalance_draft": ToolSpec(
                "reject_rebalance_draft",
                "planner",
                AuthorityLevel.A4,
                "high",
                True,
                {"draft_id": "str", "note": "str?"},
                ["rebalance_draft", "audit_log"],
            ),
            "list_pre_trade_reviews": ToolSpec(
                "list_pre_trade_reviews",
                "planner",
                AuthorityLevel.A3,
                "medium",
                True,
                {"draft_id": "str?", "symbol": "str?", "status": "str?", "limit": "int?"},
                ["pre_trade_review", "rebalance_draft", "audit_log"],
            ),
            "list_paper_orders": ToolSpec(
                "list_paper_orders",
                "execution",
                AuthorityLevel.A3,
                "medium",
                True,
                {"review_id": "str?", "draft_id": "str?", "symbol": "str?", "status": "str?", "limit": "int?"},
                ["paper_order", "pre_trade_review", "audit_log"],
            ),
            "get_paper_portfolio": ToolSpec(
                "get_paper_portfolio",
                "paper-portfolio",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                ["paper_portfolio_projection", "paper_order", "app_config:paper_portfolio_baseline", "provider_router"],
            ),
            "analyze_paper_performance": ToolSpec(
                "analyze_paper_performance",
                "paper-portfolio",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                [
                    "paper_portfolio_projection",
                    "paper_portfolio_snapshot",
                    "paper_order",
                    "app_config:paper_portfolio_baseline",
                    "provider_router",
                ],
            ),
            "create_paper_portfolio_snapshot": ToolSpec(
                "create_paper_portfolio_snapshot",
                "paper-portfolio",
                AuthorityLevel.A3,
                "medium",
                True,
                {},
                ["paper_portfolio_snapshot", "paper_portfolio_projection", "audit_log"],
            ),
            "list_decision_journal": ToolSpec(
                "list_decision_journal",
                "decision-journal",
                AuthorityLevel.A3,
                "low",
                True,
                {"symbol": "str?", "status": "str?", "source_type": "str?", "limit": "int?"},
                ["decision_journal_entry", "rebalance_draft", "pre_trade_review", "paper_order"],
            ),
            "get_decision_journal_entry": ToolSpec(
                "get_decision_journal_entry",
                "decision-journal",
                AuthorityLevel.A3,
                "low",
                True,
                {"entry_id": "str"},
                ["decision_journal_entry", "rebalance_draft", "pre_trade_review", "paper_order"],
            ),
            "summarize_decision_outcomes": ToolSpec(
                "summarize_decision_outcomes",
                "decision-journal",
                AuthorityLevel.A3,
                "low",
                True,
                {"symbol": "str?"},
                ["decision_journal_entry", "paper_order", "paper_portfolio_snapshot"],
            ),
            "list_review_inbox": ToolSpec(
                "list_review_inbox",
                "review-inbox",
                AuthorityLevel.A3,
                "low",
                True,
                {"priority": "str?", "limit": "int?"},
                [
                    "review_inbox_state",
                    "rebalance_draft",
                    "pre_trade_review",
                    "decision_journal_entry",
                    "monitor_event",
                    "report",
                    "paper_portfolio_snapshot",
                ],
            ),
            "summarize_review_inbox": ToolSpec(
                "summarize_review_inbox",
                "review-inbox",
                AuthorityLevel.A3,
                "low",
                True,
                {},
                [
                    "review_inbox_state",
                    "rebalance_draft",
                    "pre_trade_review",
                    "decision_journal_entry",
                    "monitor_event",
                    "report",
                    "paper_portfolio_snapshot",
                ],
            ),
            "dismiss_inbox_item": ToolSpec(
                "dismiss_inbox_item",
                "review-inbox",
                AuthorityLevel.A3,
                "low",
                True,
                {"item_key": "str"},
                ["review_inbox_state", "audit_log"],
            ),
            "snooze_inbox_item": ToolSpec(
                "snooze_inbox_item",
                "review-inbox",
                AuthorityLevel.A3,
                "low",
                True,
                {"item_key": "str", "snoozed_until": "str"},
                ["review_inbox_state", "audit_log"],
            ),
            "mark_inbox_item_done": ToolSpec(
                "mark_inbox_item_done",
                "review-inbox",
                AuthorityLevel.A3,
                "low",
                True,
                {"item_key": "str"},
                ["review_inbox_state", "audit_log"],
            ),
            "get_monitor_events": ToolSpec(
                "get_monitor_events",
                "monitor",
                AuthorityLevel.A2,
                "low",
                True,
                {"symbol": "str?", "severity": "str?", "limit": "int?"},
                ["monitor_event", "monitor_status"],
            ),
            "get_monitor_rules": ToolSpec(
                "get_monitor_rules",
                "monitor",
                AuthorityLevel.A2,
                "low",
                True,
                {},
                ["monitor_rule", "monitor_status"],
            ),
            "evaluate_monitor_rules": ToolSpec(
                "evaluate_monitor_rules",
                "monitor",
                AuthorityLevel.A2,
                "medium",
                True,
                {"source": "str?", "force": "bool?"},
                ["monitor_rule", "monitor_event", "monitor_status"],
            ),
            "list_strategies": ToolSpec(
                "list_strategies",
                "strategy",
                AuthorityLevel.A2,
                "low",
                True,
                {},
                ["strategy_spec"],
            ),
            "run_strategy_backtest": ToolSpec(
                "run_strategy_backtest",
                "strategy",
                AuthorityLevel.A3,
                "medium",
                True,
                {"strategy_id": "str", "period": "dict?", "universe": "list[str]?", "parameters": "dict?"},
                ["strategy_spec", "backtest_run", "provider_router"],
            ),
            "get_backtest_result": ToolSpec(
                "get_backtest_result",
                "strategy",
                AuthorityLevel.A2,
                "low",
                True,
                {"run_id": "str?", "strategy_id": "str?"},
                ["backtest_run", "strategy_snapshot"],
            ),
            "list_report_templates": ToolSpec(
                "list_report_templates",
                "report",
                AuthorityLevel.A2,
                "low",
                True,
                {},
                ["report_template", "code_registry"],
            ),
            "generate_report": ToolSpec(
                "generate_report",
                "report",
                AuthorityLevel.A2,
                "medium",
                True,
                {"report_type": "str", "source_type": "str", "source_id": "str", "template_id": "str?"},
                ["report", "report_quality_check", "audit_log"],
            ),
            "get_report_quality": ToolSpec(
                "get_report_quality",
                "report",
                AuthorityLevel.A2,
                "low",
                True,
                {"report_id": "str"},
                ["report_quality_check", "audit_log"],
            ),
            "add_watchlist_item": ToolSpec(
                "add_watchlist_item",
                "research",
                AuthorityLevel.A2,
                "low",
                True,
                {"symbol": "str", "name": "str?", "group_name": "str?"},
                ["watchlist_item", "local_sqlite"],
            ),
            "remove_watchlist_item": ToolSpec(
                "remove_watchlist_item",
                "research",
                AuthorityLevel.A2,
                "low",
                True,
                {"symbol": "str"},
                ["watchlist_item", "local_sqlite"],
            ),
            "upsert_holding": ToolSpec(
                "upsert_holding",
                "portfolio",
                AuthorityLevel.A3,
                "medium",
                True,
                {"symbol": "str", "name": "str", "quantity": "float", "cost": "float", "market_value": "float?", "weight_pct": "float?"},
                ["holding_position", "local_sqlite", "audit_log"],
            ),
            "place_real_order": ToolSpec(
                "place_real_order",
                "execution",
                AuthorityLevel.A5,
                "blocked",
                False,
                {"symbol": "str", "quantity": "float"},
                ["permission_guard:real_order_disabled"],
            ),
            "get_worldcup_matches": ToolSpec(
                "get_worldcup_matches",
                "worldcup",
                AuthorityLevel.A2,
                "low",
                True,
                {"match_id": "str?", "stage": "str?", "status": "str?"},
                ["worldcup_match"],
            ),
            "get_worldcup_odds": ToolSpec(
                "get_worldcup_odds",
                "worldcup",
                AuthorityLevel.A2,
                "low",
                True,
                {"match_id": "str"},
                ["worldcup_odds", "worldcup_match"],
            ),
            "get_worldcup_analysis": ToolSpec(
                "get_worldcup_analysis",
                "worldcup",
                AuthorityLevel.A2,
                "low",
                True,
                {"match_id": "str"},
                ["worldcup_match", "worldcup_odds", "worldcup_analysis"],
            ),
            "create_worldcup_prediction": ToolSpec(
                "create_worldcup_prediction",
                "worldcup",
                AuthorityLevel.A3,
                "medium",
                True,
                {"match_id": "str", "home_score": "int", "away_score": "int", "confidence": "float?"},
                ["worldcup_prediction", "worldcup_match"],
            ),
            "create_worldcup_bet": ToolSpec(
                "create_worldcup_bet",
                "worldcup",
                AuthorityLevel.A3,
                "medium",
                True,
                {"match_id": "str", "bet_type": "str", "odds": "float", "stake": "float", "probability": "float"},
                ["worldcup_bet", "worldcup_match", "worldcup_odds"],
            ),
            "update_worldcup_bet": ToolSpec(
                "update_worldcup_bet",
                "worldcup",
                AuthorityLevel.A3,
                "medium",
                True,
                {"bet_id": "str", "status": "str", "profit": "float?"},
                ["worldcup_bet"],
            ),
            "delete_worldcup_bet": ToolSpec(
                "delete_worldcup_bet",
                "worldcup",
                AuthorityLevel.A3,
                "medium",
                True,
                {"bet_id": "str"},
                ["worldcup_bet"],
            ),
            "list_worldcup_bets": ToolSpec(
                "list_worldcup_bets",
                "worldcup",
                AuthorityLevel.A2,
                "low",
                True,
                {"status": "str?", "limit": "int?"},
                ["worldcup_bet"],
            ),
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._specs[name].to_dict() for name in self._handlers]

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    def resolve_confirmed_draft_id(self, symbol: str | None) -> str | None:
        if not symbol:
            return None
        items = self.rebalance_draft_service.list(
            symbol=symbol.upper(),
            status=RebalanceDraftStatus.CONFIRMED_NO_EXECUTION.value,
            limit=1,
        )
        if not items:
            return None
        return items[0].draft_id

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        authority_level: AuthorityLevel | str,
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        call_id: str | None = None,
        source_mode: str | None = None,
    ) -> dict[str, Any]:
        if name not in self._handlers:
            raise KeyError(name)
        spec = self._specs[name]
        level = authority_level if isinstance(authority_level, AuthorityLevel) else AuthorityLevel(authority_level)
        args = arguments or {}

        policy = self.execution_policy.decide(name)
        if policy.mode == ExecutionMode.BLOCKED:
            self.permission_guard.block_real_order()
            raise PermissionDenied(policy.reason)
        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            return {
                "tool": name,
                "authority_level": spec.required_authority.value,
                "risk": spec.risk,
                "result": {"status": "needs_confirmation", "reason": policy.reason, "next_action": policy.next_action},
                "evidence_refs": spec.evidence_refs,
                "execution_mode": policy.mode.value,
            }

        try:
            self.permission_guard.require(level, spec.required_authority, name)
        except PermissionDenied as exc:
            self._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=args, task_id=task_id, run_id=run_id, call_id=call_id,
                source_mode=source_mode, evidence_refs=spec.evidence_refs,
                error=str(exc),
            )
            raise

        try:
            result = self._handlers[name](args)
        except Exception as exc:
            self._record_execution(
                tool=name, domain=spec.domain, status="failed",
                authority_level=spec.required_authority.value,
                arguments=args, task_id=task_id, run_id=run_id, call_id=call_id,
                source_mode=source_mode, evidence_refs=spec.evidence_refs,
                error=str(exc),
            )
            raise

        self._record_execution(
            tool=name, domain=spec.domain, status="succeeded",
            authority_level=spec.required_authority.value,
            arguments=args, task_id=task_id, run_id=run_id, call_id=call_id,
            source_mode=source_mode, evidence_refs=spec.evidence_refs,
            result=result,
        )

        return {
            "tool": name,
            "authority_level": spec.required_authority.value,
            "risk": spec.risk,
            "result": result,
            "evidence_refs": spec.evidence_refs,
            "execution_mode": policy.mode.value,
        }

    def _record_execution(
        self,
        *,
        tool: str,
        domain: str,
        status: str,
        authority_level: str,
        arguments: dict[str, Any],
        task_id: str | None = None,
        run_id: str | None = None,
        call_id: str | None = None,
        source_mode: str | None = None,
        evidence_refs: list[str],
        result: Any = None,
        error: str | None = None,
    ) -> None:
        if not self.tool_execution_service:
            return
        self.tool_execution_service.record(
            tool=tool,
            domain=domain,
            status=status,
            authority_level=authority_level,
            arguments=arguments,
            task_id=task_id,
            run_id=run_id,
            call_id=call_id,
            source_mode=source_mode,
            evidence_refs=evidence_refs,
            result=result,
            error=error,
        )

    def _get_stock_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return model_to_dict(self.context_builder.build_stock_context(str(arguments.get("symbol") or "AAPL")))

    def _get_daily_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return get_daily_history(str(arguments.get("symbol") or "AAPL"), int(arguments.get("days") or 30))

    def _search_stock_intel(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return search_stock_intel(str(arguments.get("symbol") or "AAPL"), str(arguments.get("query") or ""))

    def _get_portfolio_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return summarize_portfolio(self.repo.list_holdings())

    def _get_active_risk_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return model_to_dict(self.risk_policy_service.get_active_policy())

    def _list_risk_policies(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"items": [model_to_dict(item) for item in self.risk_policy_service.list_policies()]}

    def _evaluate_policy_risk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.risk_policy_service.analyze_portfolio_risk(self.repo.list_holdings())

    def _analyze_portfolio_risk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._evaluate_policy_risk(arguments)

    def _get_monitor_events(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").upper() or None
        severity = str(arguments.get("severity") or "") or None
        limit = int(arguments.get("limit") or 10)
        items = self.monitor_service.list_events(symbol=symbol, severity=severity, limit=limit)
        explanation = self.monitor_service.explain_event(event=items[0]) if items else self.monitor_service.empty_explanation()
        return {
            "items": [model_to_dict(item) for item in items],
            "status": model_to_dict(self.monitor_service.get_status()),
            "explanation": explanation,
        }

    def _get_monitor_rules(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "items": [model_to_dict(item) for item in self.monitor_service.list_rules()],
            "status": model_to_dict(self.monitor_service.get_status()),
        }

    def _evaluate_monitor_rules(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source = str(arguments.get("source") or "tool")
        force = bool(arguments.get("force", False))
        return self.monitor_service.evaluate_once(source=source, force=force)

    def _list_strategies(self, arguments: dict[str, Any]) -> dict[str, Any]:
        enabled = arguments.get("enabled")
        if enabled is not None:
            enabled = bool(enabled)
        return {"items": [model_to_dict(item) for item in self.strategy_service.list_strategies(enabled=enabled)]}

    def _run_strategy_backtest(self, arguments: dict[str, Any]) -> dict[str, Any]:
        strategy_id = str(arguments.get("strategy_id") or "concentration-control")
        run = self.strategy_service.run_backtest(
            strategy_id,
            period=arguments.get("period"),
            universe=arguments.get("universe"),
            parameters=arguments.get("parameters"),
        )
        return model_to_dict(run)

    def _get_backtest_result(self, arguments: dict[str, Any]) -> dict[str, Any]:
        run_id = str(arguments.get("run_id") or "")
        if run_id:
            return model_to_dict(self.strategy_service.get_backtest(run_id))
        strategy_id = str(arguments.get("strategy_id") or "concentration-control")
        runs = self.strategy_service.list_backtests(strategy_id, limit=1)
        if not runs:
            raise KeyError(f"backtest not found for strategy {strategy_id}")
        return model_to_dict(runs[0])

    def _list_report_templates(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"items": [model_to_dict(item) for item in self.report_service.list_templates()]}

    def _generate_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        report = self.report_service.generate(
            ReportGenerateRequest(
                report_type=str(arguments.get("report_type") or "stock_research"),
                source_type=str(arguments.get("source_type") or "stock"),
                source_id=str(arguments.get("source_id") or arguments.get("symbol") or "AAPL"),
                template_id=str(arguments["template_id"]) if arguments.get("template_id") else None,
                title=str(arguments["title"]) if arguments.get("title") else None,
                options=dict(arguments.get("options") or {}),
            )
        )
        return model_to_dict(report)

    def _get_report_quality(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.report_service.get_quality(str(arguments.get("report_id") or ""))

    def _generate_draft_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        draft = self.rebalance_draft_service.create(
            {
                "symbol": str(arguments.get("symbol") or "AAPL"),
                "target_weight_pct": float(arguments.get("target_weight_pct") or 15),
            },
            source_mode="tool_bridge",
        )
        return self.rebalance_draft_service.to_tool_result(draft)

    def _list_rebalance_drafts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.rebalance_draft_service.list(
            symbol=str(arguments.get("symbol") or "").upper() or None,
            status=str(arguments.get("status") or "") or None,
            limit=int(arguments.get("limit") or 20),
        )
        return {"items": [model_to_dict(item) for item in items], "count": len(items)}

    def _get_rebalance_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(arguments.get("draft_id") or "").strip()
        if not draft_id:
            drafts = self.rebalance_draft_service.list(limit=1)
            if not drafts:
                raise ValueError("no drafts found")
            draft_id = drafts[0].draft_id
        return model_to_dict(self.rebalance_draft_service.get(draft_id))

    def _confirm_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(arguments.get("draft_id") or "").strip()
        if not draft_id:
            raise ValueError("confirm_rebalance_draft requires an explicit draft_id")
        draft = self.rebalance_draft_service.get(draft_id)
        if draft.status == RebalanceDraftStatus.CONFIRMED_NO_EXECUTION:
            return model_to_dict(draft)
        note = str(arguments.get("note") or "")
        draft = self.rebalance_draft_service.confirm(
            draft_id,
            RebalanceDraftDecisionNoteRequest(note=note),
        )
        return model_to_dict(draft)

    def _reject_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(arguments.get("draft_id") or "").strip()
        if not draft_id:
            raise ValueError("reject_rebalance_draft requires an explicit draft_id")
        note = str(arguments.get("note") or "")
        draft = self.rebalance_draft_service.reject(
            draft_id,
            RebalanceDraftDecisionNoteRequest(note=note),
        )
        return model_to_dict(draft)

    def _add_watchlist_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from backend.schemas import WatchlistItem as WI
        symbol = str(arguments.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("add_watchlist_item requires a symbol")
        item = WI(
            symbol=symbol,
            name=str(arguments.get("name") or ""),
            group_name=str(arguments.get("group_name") or ""),
        )
        saved = self.repo.upsert_watchlist_item(item)
        return model_to_dict(saved)

    def _remove_watchlist_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("remove_watchlist_item requires a symbol")
        deleted = self.repo.delete_watchlist_item(symbol)
        return {"symbol": symbol, "deleted": deleted}

    def _upsert_holding(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("upsert_holding requires a symbol")
        name = str(arguments.get("name") or "")
        if not name:
            raise ValueError("upsert_holding requires a name")
        quantity = float(arguments.get("quantity") or 0)
        cost = float(arguments.get("cost") or 0)
        market_value = arguments.get("market_value")
        weight_pct = arguments.get("weight_pct")
        if market_value is not None:
            market_value = float(market_value)
        else:
            market_value = round(quantity * cost, 2)
        if weight_pct is not None:
            weight_pct = float(weight_pct)
        position = HoldingPosition(
            symbol=symbol,
            name=name,
            quantity=quantity,
            market_value=market_value,
            weight_pct=weight_pct if weight_pct is not None else 0.0,
            cost=cost,
        )
        saved = self.repo.upsert_holding(position)
        return model_to_dict(saved)

    def _create_pre_trade_review(self, arguments: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(arguments.get("draft_id") or "").strip()
        if not draft_id:
            drafts = self.rebalance_draft_service.list(
                status="confirmed_no_execution",
                limit=1,
            )
            if not drafts:
                raise ValueError("no confirmed drafts found; confirm a draft first before creating a review")
            draft_id = drafts[0].draft_id
        review = self.pre_trade_review_service.create(
            draft_id=draft_id,
            source_mode="tool_bridge",
            strict_status=True,
        )
        return self.pre_trade_review_service.to_tool_result(review)

    def _list_pre_trade_reviews(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.pre_trade_review_service.list(
            draft_id=str(arguments.get("draft_id") or "") or None,
            symbol=str(arguments.get("symbol") or "").upper() or None,
            status=str(arguments.get("status") or "") or None,
            limit=int(arguments.get("limit") or 20),
        )
        return {"items": [model_to_dict(item) for item in items], "count": len(items)}

    def _list_paper_orders(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.paper_trading_service.list(
            review_id=str(arguments.get("review_id") or "") or None,
            draft_id=str(arguments.get("draft_id") or "") or None,
            symbol=str(arguments.get("symbol") or "").upper() or None,
            status=str(arguments.get("status") or "") or None,
            limit=int(arguments.get("limit") or 20),
        )
        return {"items": [model_to_dict(item) for item in items], "count": len(items)}

    def _get_paper_portfolio(self, arguments: dict[str, Any]) -> dict[str, Any]:
        projection = self.paper_portfolio_service.get_projection()
        return {
            "summary": self.paper_portfolio_service.get_summary(projection),
            "projection": model_to_dict(projection),
        }

    def _analyze_paper_performance(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.paper_portfolio_service.get_performance()

    def _create_paper_portfolio_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return model_to_dict(self.paper_portfolio_service.create_snapshot(source_mode="tool_bridge"))

    def _list_decision_journal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.decision_journal_service.list_entries(
            symbol=str(arguments.get("symbol") or "").upper() or None,
            status=str(arguments.get("status") or "") or None,
            source_type=str(arguments.get("source_type") or "") or None,
            limit=int(arguments.get("limit") or 20),
        )
        return {"items": items, "count": len(items)}

    def _get_decision_journal_entry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.decision_journal_service.get_entry(str(arguments.get("entry_id") or ""))

    def _summarize_decision_outcomes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.decision_journal_service.summarize_outcomes(
            symbol=str(arguments.get("symbol") or "").upper() or None,
        )

    def _list_review_inbox(self, arguments: dict[str, Any]) -> dict[str, Any]:
        items = self.review_inbox_service.list_items(
            priority=str(arguments.get("priority") or "") or None,
            limit=int(arguments.get("limit")) if arguments.get("limit") is not None else None,
        )
        return {"items": [model_to_dict(item) for item in items], "count": len(items)}

    def _summarize_review_inbox(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return model_to_dict(self.review_inbox_service.summarize())

    def _dismiss_inbox_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        item_key = str(arguments.get("item_key") or "").strip()
        if not item_key:
            items = self.review_inbox_service.list_items(limit=1)
            if not items:
                raise ValueError("no inbox items to dismiss")
            item_key = items[0].item_key
        return model_to_dict(self.review_inbox_service.dismiss(item_key))

    def _snooze_inbox_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        item_key = str(arguments.get("item_key") or "").strip()
        snoozed_until = str(arguments.get("snoozed_until") or "")
        if not item_key:
            items = self.review_inbox_service.list_items(limit=1)
            if not items:
                raise ValueError("no inbox items to snooze")
            item_key = items[0].item_key
        if not snoozed_until:
            snoozed_until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        return model_to_dict(self.review_inbox_service.snooze(item_key, snoozed_until=snoozed_until))

    def _mark_inbox_item_done(self, arguments: dict[str, Any]) -> dict[str, Any]:
        item_key = str(arguments.get("item_key") or "").strip()
        if not item_key:
            items = self.review_inbox_service.list_items(limit=1)
            if not items:
                raise ValueError("no inbox items to mark done")
            item_key = items[0].item_key
        return model_to_dict(self.review_inbox_service.mark_done(item_key))

    def _place_real_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.permission_guard.block_real_order()
        return {}

    def _get_worldcup_matches(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match_id = str(arguments.get("match_id") or "") or None
        stage = str(arguments.get("stage") or "") or None
        status = str(arguments.get("status") or "") or None
        items = self.worldcup_service.get_matches(
            match_id=match_id,
            stage=stage,
            status=status,
        )
        return {"items": items, "count": len(items)}

    def _get_worldcup_odds(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match_id = str(arguments.get("match_id") or "")
        return self.worldcup_service.get_odds(match_id)

    def _get_worldcup_analysis(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match_id = str(arguments.get("match_id") or "")
        return self.worldcup_service.get_analysis(match_id)

    def _create_worldcup_prediction(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match_id = str(arguments.get("match_id") or "")
        home_score = int(arguments.get("home_score") or 0)
        away_score = int(arguments.get("away_score") or 0)
        confidence = float(arguments.get("confidence") or 0.5)
        return self.worldcup_service.create_prediction(
            match_id=match_id,
            home_score=home_score,
            away_score=away_score,
            confidence=confidence,
        )

    def _create_worldcup_bet(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match_id = str(arguments.get("match_id") or "")
        bet_type = str(arguments.get("bet_type") or "home")
        odds = float(arguments.get("odds") or 1.0)
        stake = float(arguments.get("stake") or 0)
        probability = float(arguments.get("probability") or 50)
        return self.worldcup_service.create_bet(
            match_id=match_id,
            bet_type=bet_type,
            odds=odds,
            stake=stake,
            probability=probability,
        )

    def _update_worldcup_bet(self, arguments: dict[str, Any]) -> dict[str, Any]:
        bet_id = str(arguments.get("bet_id") or "")
        status = str(arguments.get("status") or "pending")
        profit = arguments.get("profit")
        return self.worldcup_service.update_bet(
            bet_id=bet_id,
            status=status,
            profit=profit,
        )

    def _delete_worldcup_bet(self, arguments: dict[str, Any]) -> dict[str, Any]:
        bet_id = str(arguments.get("bet_id") or "")
        return self.worldcup_service.delete_bet(bet_id)

    def _list_worldcup_bets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        status = str(arguments.get("status") or "") or None
        limit = int(arguments.get("limit") or 20)
        items = self.worldcup_service.list_bets(status=status, limit=limit)
        return {"items": items, "count": len(items)}

from __future__ import annotations

from typing import Any

from backend.app_services.context_builder import ContextBuilder
from backend.app_services.context_cache import ContextCache
from backend.app_services.monitor_service import MonitorService
from backend.app_services.review_inbox_service import ReviewInboxService
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import model_to_dict
from backend.stock_domain.portfolio_tools import summarize_portfolio

# Intent → required context sections mapping.
# Controls which data is loaded when an intent is known.
# "overview" is the default fallback when intent is unknown or not matched.
INTENT_TO_CONTEXT_SECTIONS: dict[str, set[str]] = {
    "stock_research":           {"holdings", "risk_policy"},
    "risk_review":              {"holdings", "risk_policy"},
    "rebalance_plan":           {"holdings", "risk_policy"},
    "strategy_backtest":        {"holdings", "risk_policy"},
    "monitor_event":            {"monitor"},
    "report_write":             {"reports"},
    "review_inbox":             {"inbox"},
    "decision_journal_review":  {"journal"},
    "paper_portfolio_review":   {"paper_portfolio"},
    "pre_trade_review":         {"holdings", "risk_policy"},
    "execution_request":        {},    # blocked — minimal context
    "copilot_chat":             {"overview"},
}


class CopilotContextBuilder:
    def __init__(
        self,
        *,
        repo: WorkbenchRepository,
        context_builder: ContextBuilder,
        monitor_service: MonitorService,
        risk_policy_service: RiskPolicyService,
        review_inbox_service: ReviewInboxService,
        cache: ContextCache | None = None,
    ) -> None:
        self.repo = repo
        self.context_builder = context_builder
        self.monitor_service = monitor_service
        self.risk_policy_service = risk_policy_service
        self.review_inbox_service = review_inbox_service
        self._cache = cache or ContextCache()

    def build(self, *, page: str, symbol: str | None = None, intent: str | None = None) -> dict[str, Any]:
        normalized_page = page if page in {
            "overview",
            "holdings",
            "monitor",
            "reports",
            "tasks",
            "stock",
            "journal",
            "inbox",
        } else "overview"
        # Determine which sections to load based on intent
        sections = INTENT_TO_CONTEXT_SECTIONS.get(intent, {normalized_page}) if intent else {normalized_page}
        payload: dict[str, Any] = {"page": normalized_page}

        if symbol and (sections & {"holdings", "stock", "risk_policy"} or normalized_page == "stock"):
            payload["symbol_summary"] = self._symbol_summary(symbol)

        if "holdings" in sections:
            payload["holdings"] = self._holdings_summary()
        if "risk_policy" in sections:
            payload["active_risk_policy"] = self._policy_summary()
        if "monitor" in sections:
            payload["monitor"] = self._monitor_summary()
        if "reports" in sections:
            payload["reports"] = self._reports_summary(limit=5)
        if "tasks" in sections or normalized_page == "tasks":
            payload["tasks"] = self._tasks_summary(limit=5)
        if "journal" in sections:
            payload["journal"] = self._build_journal()
        if "inbox" in sections:
            payload["inbox"] = self._inbox_summary()
        if "overview" in sections or normalized_page == "overview":
            payload["overview"] = self._build_overview_content()
        if "paper_portfolio" in sections:
            payload["paper_portfolio"] = self._build_paper_portfolio()

        return payload

    def _build_overview_content(self) -> dict[str, Any]:
        return {
            "active_risk_policy": self._policy_summary(),
            "holdings": self._holdings_summary(),
            "monitor": self._monitor_summary(),
            "reports": self._reports_summary(limit=3),
            "tasks": self._tasks_summary(limit=3),
            "inbox": self._inbox_summary(),
        }

    def _build_paper_portfolio(self) -> dict[str, Any]:
        try:
            from backend.app_services.paper_portfolio_service import PaperPortfolioService
            svc = PaperPortfolioService(repo=self.repo, context_builder=self.context_builder)
            projection = svc.get_projection()
            return {
                "market_value": projection.market_value,
                "cash_estimate": projection.cash_estimate,
                "equity_estimate": projection.equity_estimate,
                "pnl_estimate": projection.pnl_estimate,
                "position_count": len(projection.positions),
            }
        except Exception:
            return {"status": "unavailable"}

    def _build_journal(self) -> dict[str, Any]:
        items = self.repo.list_decision_journal_entries(limit=5)
        return {
            "items": [
                {
                    "entry_id": item.entry_id,
                    "decision_id": item.decision_id,
                    "symbol": item.symbol,
                    "status": item.status,
                    "source_type": item.source_type,
                    "has_snapshot": bool(item.snapshot_id),
                    "has_report": bool(item.report_id),
                    "updated_at": item.updated_at,
                }
                for item in items
            ]
        }

    def _symbol_summary(self, symbol: str) -> dict[str, Any]:
        context = self.context_builder.build_stock_context(symbol)
        return {
            "symbol": context.symbol,
            "name": context.name,
            "market": context.market,
            "industry": context.industry,
            "sector": context.sector,
            "price": {
                "last": context.price.last,
                "change_pct": context.price.change_pct,
                "updated_at": context.price.updated_at,
                "source": context.price.source,
            },
            "relation": model_to_dict(context.relation),
            "holding": {
                "weight_pct": context.holding.weight_pct,
                "market_value": context.holding.market_value,
            },
            "ai_state": model_to_dict(context.ai_state),
            "latest_report": model_to_dict(context.latest_report),
        }

    def _policy_summary(self) -> dict[str, Any]:
        cached = self._cache.get("policy_summary")
        if cached:
            return cached
        policy = self.risk_policy_service.get_active_policy()
        result = {
            "policy_id": policy.policy_id,
            "name": policy.name,
            "version": policy.version,
            "updated_at": policy.updated_at,
            "rules": {
                "single_position_max_weight_pct": policy.rules.single_position_max_weight_pct,
                "single_position_warning_weight_pct": policy.rules.single_position_warning_weight_pct,
                "sector_max_weight_pct": policy.rules.sector_max_weight_pct,
                "draft_valid_hours": policy.rules.draft_valid_hours,
            },
        }
        self._cache.set("policy_summary", result)
        return result

    def _holdings_summary(self) -> dict[str, Any]:
        cached = self._cache.get("holdings_summary")
        if cached:
            return cached
        holdings = self.repo.list_holdings()
        summary = summarize_portfolio(holdings)
        top_positions = []
        for item in holdings[:3]:
            top_positions.append(
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "weight_pct": item.weight_pct,
                    "market_value": item.market_value,
                }
            )
        result = {
            "position_count": len(holdings),
            "market_value_total": summary["total_value"],
            "top_positions": top_positions,
            "risk_count": sum(1 for item in holdings if item.weight_pct >= 12),
        }
        self._cache.set("holdings_summary", result)
        return result

    def _monitor_summary(self) -> dict[str, Any]:
        cached = self._cache.get("monitor_summary")
        if cached:
            return cached
        status = self.monitor_service.get_status()
        items = self.monitor_service.list_events(limit=5)
        result = {
            "status": {
                "status": status.status,
                "last_checked_at": status.last_checked_at,
                "last_matched_at": status.last_matched_at,
                "last_error": status.last_error,
            },
            "items": [
                {
                    "event_id": item.event_id,
                    "symbol": item.symbol,
                    "title": item.title,
                    "severity": item.severity,
                    "triggered_at": item.triggered_at,
                }
                for item in items
            ],
        }
        self._cache.set("monitor_summary", result)
        return result

    def _reports_summary(self, *, limit: int) -> dict[str, Any]:
        cached = self._cache.get("reports_summary")
        if cached:
            return cached
        reports = self.repo.list_reports(limit=limit)
        result = {
            "items": [
                {
                    "report_id": item.report_id,
                    "title": item.title,
                    "symbol": item.symbol,
                    "report_type": item.report_type,
                    "quality_status": item.quality_status,
                    "evidence_count": item.evidence_count,
                    "valid_until": item.valid_until,
                    "created_at": item.created_at,
                }
                for item in reports
            ]
        }
        self._cache.set("reports_summary", result)
        return result

    def _tasks_summary(self, *, limit: int) -> dict[str, Any]:
        cached = self._cache.get("tasks_summary")
        if cached:
            return cached
        tasks = self.repo.list_tasks()[:limit]
        result = {
            "items": [
                {
                    "task_id": item.task_id,
                    "title": item.title,
                    "source": item.source,
                    "status": item.status,
                    "progress": item.progress,
                    "current_step": item.current_step,
                    "run_id": item.run_id,
                }
                for item in tasks
            ]
        }
        self._cache.set("tasks_summary", result)
        return result

    def _inbox_summary(self) -> dict[str, Any]:
        cached = self._cache.get("inbox_summary")
        if cached:
            return cached
        summary = self.review_inbox_service.summarize()
        items = self.review_inbox_service.list_items(limit=5)
        result = {
            "summary": model_to_dict(summary),
            "items": [
                {
                    "item_key": item.item_key,
                    "title": item.title,
                    "priority": item.priority,
                    "severity": item.severity,
                    "status": item.status.value,
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "occurred_at": item.occurred_at,
                }
                for item in items
            ],
        }
        self._cache.set("inbox_summary", result)
        return result

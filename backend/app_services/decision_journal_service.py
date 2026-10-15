from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.paper_portfolio_service import PaperPortfolioService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    DecisionJournalEntry,
    PaperOrder,
    PaperPortfolioSnapshot,
    PreTradeReview,
    RebalanceDraft,
    Report,
    model_to_dict,
    now_iso,
)


class DecisionJournalSnapshotNotFoundError(ValueError):
    pass


class DecisionJournalSnapshotConflictError(ValueError):
    pass


class DecisionJournalCloseConflictError(ValueError):
    pass


class DecisionJournalService:
    def __init__(
        self,
        *,
        repo: WorkbenchRepository,
        audit_service: AuditService,
        paper_portfolio_service: PaperPortfolioService,
    ) -> None:
        self.repo = repo
        self.audit_service = audit_service
        self.paper_portfolio_service = paper_portfolio_service

    def upsert_from_draft(self, draft: RebalanceDraft) -> DecisionJournalEntry:
        return self._upsert_entry(
            decision_id=draft.decision_id,
            symbol=draft.symbol,
            status="open",
            source_type="rebalance_draft",
            draft_id=draft.draft_id,
        )

    def upsert_from_review(self, review: PreTradeReview) -> DecisionJournalEntry:
        draft = self._get_draft(review.source_draft_id)
        existing = self.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
        status = existing.status if existing and existing.status in {"paper_tracked", "closed"} else "reviewed"
        return self._upsert_entry(
            decision_id=draft.decision_id,
            symbol=review.symbol,
            status=status,
            source_type="pre_trade_review",
            draft_id=review.source_draft_id,
            review_id=review.review_id,
        )

    def upsert_from_paper_order(self, order: PaperOrder) -> DecisionJournalEntry:
        draft = self._get_draft(order.source_draft_id)
        existing = self.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
        status = "closed" if existing and existing.status == "closed" else "paper_tracked"
        return self._upsert_entry(
            decision_id=draft.decision_id,
            symbol=order.symbol,
            status=status,
            source_type="paper_order",
            draft_id=order.source_draft_id,
            review_id=order.review_id,
            paper_order_id=order.order_id,
        )

    def link_snapshot(self, entry_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
        entry = self.repo.get_decision_journal_entry(entry_id)
        if not entry:
            raise KeyError(entry_id)
        snapshot = self._resolve_snapshot(snapshot_id)
        linked_report_id = entry.report_id or self._latest_snapshot_report_id(snapshot.snapshot_id)
        if entry.snapshot_id == snapshot.snapshot_id and entry.report_id == linked_report_id:
            return self.serialize_entry(entry)
        conflict = self.repo.get_decision_journal_entry_by_snapshot_id(snapshot.snapshot_id)
        if conflict and conflict.entry_id != entry.entry_id:
            raise DecisionJournalSnapshotConflictError(
                f"snapshot {snapshot.snapshot_id} is already linked to journal entry {conflict.entry_id}"
            )
        linked = self._save_entry(
            entry.model_copy(
                update={
                    "snapshot_id": snapshot.snapshot_id,
                    "report_id": linked_report_id,
                    "source_type": "paper_portfolio_review" if linked_report_id else "paper_portfolio_snapshot",
                    "updated_at": now_iso(),
                }
            )
        )
        self.audit_service.record(
            "decision journal snapshot linked",
            f"{linked.entry_id} snapshot={snapshot.snapshot_id}",
            AuthorityLevel.A3,
        )
        if linked_report_id and entry.report_id != linked_report_id:
            self.audit_service.record(
                "decision journal report linked",
                f"{linked.entry_id} report={linked_report_id}",
                AuthorityLevel.A3,
            )
        return self.serialize_entry(linked)

    def close_entry(self, entry_id: str, close_note: str = "") -> dict[str, Any]:
        entry = self.repo.get_decision_journal_entry(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if entry.status == "closed":
            return self.serialize_entry(entry)
        if not entry.paper_order_id or not entry.snapshot_id:
            raise DecisionJournalCloseConflictError("decision journal entry requires paper_order_id and snapshot_id before close")
        closed = self._save_entry(
            entry.model_copy(
                update={
                    "status": "closed",
                    "closed_at": entry.closed_at or now_iso(),
                    "close_note": close_note or entry.close_note,
                    "updated_at": now_iso(),
                }
            )
        )
        self.audit_service.record(
            "decision journal entry closed",
            f"{closed.entry_id} snapshot={closed.snapshot_id} paper_order={closed.paper_order_id}",
            AuthorityLevel.A3,
        )
        return self.serialize_entry(closed)

    def auto_link_report(self, report: Report) -> DecisionJournalEntry | None:
        if report.source_type != "paper_portfolio_snapshot":
            return None
        entry = self.repo.get_decision_journal_entry_by_snapshot_id(report.source_id)
        if not entry:
            return None
        return self._link_report(entry, report.report_id)

    def list_entries(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        items = self.repo.list_decision_journal_entries(
            symbol=symbol.upper() if symbol else None,
            status=status,
            source_type=source_type,
            limit=limit,
        )
        return [self.serialize_entry(item) for item in items]

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        entry = self.repo.get_decision_journal_entry(entry_id)
        if not entry:
            raise KeyError(entry_id)
        return self.serialize_entry(entry)

    def summarize_outcomes(self, *, symbol: str | None = None) -> dict[str, Any]:
        entries = self.repo.list_decision_journal_entries(symbol=symbol.upper() if symbol else None, limit=None)
        tracked_items: list[dict[str, Any]] = []
        closed_count = 0
        for entry in entries:
            if entry.status == "closed":
                closed_count += 1
            if not entry.paper_order_id or not entry.snapshot_id:
                continue
            order = self.repo.get_paper_order(entry.paper_order_id)
            snapshot = self.repo.get_paper_portfolio_snapshot(entry.snapshot_id)
            if not order or not snapshot:
                continue
            tracked_items.append(
                {
                    "entry_id": entry.entry_id,
                    "decision_id": entry.decision_id,
                    "symbol": entry.symbol,
                    "status": entry.status,
                    "paper_order_id": order.order_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "paper_pnl": self._paper_pnl(order, snapshot),
                    "paper_return_pct": self._paper_return_pct(order, snapshot),
                    "current_price": self._current_price(order.symbol, snapshot),
                    "side": order.side,
                }
            )
        tracked_items.sort(key=lambda item: (item["paper_pnl"], item["symbol"]), reverse=True)
        paper_tracked_count = len(tracked_items)
        average_paper_pnl = (
            round(sum(item["paper_pnl"] for item in tracked_items) / paper_tracked_count, 4) if paper_tracked_count else 0.0
        )
        return {
            "total_suggestions": len(entries),
            "paper_tracked_count": paper_tracked_count,
            "closed_count": closed_count,
            "average_paper_pnl": average_paper_pnl,
            "items": tracked_items,
        }

    def serialize_entry(self, entry: DecisionJournalEntry) -> dict[str, Any]:
        draft = self.repo.get_rebalance_draft(entry.draft_id) if entry.draft_id else None
        review = self.repo.get_pre_trade_review(entry.review_id) if entry.review_id else None
        paper_order = self.repo.get_paper_order(entry.paper_order_id) if entry.paper_order_id else None
        snapshot = self.repo.get_paper_portfolio_snapshot(entry.snapshot_id) if entry.snapshot_id else None
        report = self.repo.get_report(entry.report_id) if entry.report_id else None
        outcome_summary = None
        if paper_order and snapshot:
            outcome_summary = {
                "paper_pnl": self._paper_pnl(paper_order, snapshot),
                "paper_return_pct": self._paper_return_pct(paper_order, snapshot),
                "current_price": self._current_price(paper_order.symbol, snapshot),
                "snapshot_as_of": snapshot.as_of,
                "tracked": True,
            }
        return {
            **model_to_dict(entry),
            "chain": {
                "draft": model_to_dict(draft) if draft else None,
                "review": model_to_dict(review) if review else None,
                "paper_order": model_to_dict(paper_order) if paper_order else None,
                "snapshot": model_to_dict(snapshot) if snapshot else None,
                "report": model_to_dict(report) if report else None,
            },
            "outcome_summary": outcome_summary,
        }

    def _upsert_entry(
        self,
        *,
        decision_id: str,
        symbol: str,
        status: str,
        source_type: str,
        draft_id: str | None = None,
        review_id: str | None = None,
        paper_order_id: str | None = None,
        snapshot_id: str | None = None,
        report_id: str | None = None,
    ) -> DecisionJournalEntry:
        existing = self.repo.get_decision_journal_entry_by_decision_id(decision_id)
        payload = {
            "entry_id": existing.entry_id if existing else f"journal_{uuid4().hex[:12]}",
            "decision_id": decision_id,
            "symbol": symbol.upper(),
            "status": status,
            "source_type": source_type,
            "draft_id": draft_id if draft_id is not None else (existing.draft_id if existing else None),
            "review_id": review_id if review_id is not None else (existing.review_id if existing else None),
            "paper_order_id": paper_order_id if paper_order_id is not None else (existing.paper_order_id if existing else None),
            "snapshot_id": snapshot_id if snapshot_id is not None else (existing.snapshot_id if existing else None),
            "report_id": report_id if report_id is not None else (existing.report_id if existing else None),
            "closed_at": existing.closed_at if existing else None,
            "close_note": existing.close_note if existing else None,
            "created_at": existing.created_at if existing else now_iso(),
            "updated_at": now_iso(),
        }
        saved = self._save_entry(DecisionJournalEntry(**payload))
        if not existing:
            self.audit_service.record(
                "decision journal entry created",
                f"{saved.entry_id} decision={saved.decision_id} draft={saved.draft_id}",
                AuthorityLevel.A3,
            )
        return saved

    def _save_entry(self, entry: DecisionJournalEntry) -> DecisionJournalEntry:
        return self.repo.save_decision_journal_entry(entry)

    def _link_report(self, entry: DecisionJournalEntry, report_id: str) -> DecisionJournalEntry:
        if entry.report_id == report_id:
            return entry
        linked = self._save_entry(
            entry.model_copy(
                update={
                    "report_id": report_id,
                    "source_type": "paper_portfolio_review",
                    "updated_at": now_iso(),
                }
            )
        )
        self.audit_service.record(
            "decision journal report linked",
            f"{linked.entry_id} report={report_id}",
            AuthorityLevel.A3,
        )
        return linked

    def _latest_snapshot_report_id(self, snapshot_id: str) -> str | None:
        reports = self.repo.list_reports(
            report_type="paper_portfolio_review",
            source_type="paper_portfolio_snapshot",
            source_id=snapshot_id,
            limit=1,
        )
        if not reports:
            return None
        return reports[0].report_id

    def _resolve_snapshot(self, snapshot_id: str | None) -> PaperPortfolioSnapshot:
        if snapshot_id:
            snapshot = self.repo.get_paper_portfolio_snapshot(snapshot_id)
            if not snapshot:
                raise DecisionJournalSnapshotNotFoundError(snapshot_id)
            return snapshot
        baseline = self.paper_portfolio_service.get_baseline()
        snapshot = next(
            iter(self.repo.list_paper_portfolio_snapshots(baseline_id=baseline.baseline_id, limit=1)),
            None,
        )
        if not snapshot:
            raise DecisionJournalSnapshotNotFoundError("latest")
        return snapshot

    def _get_draft(self, draft_id: str) -> RebalanceDraft:
        draft = self.repo.get_rebalance_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        return draft

    def _current_price(self, symbol: str, snapshot: PaperPortfolioSnapshot) -> float:
        projection = dict(snapshot.payload)
        quotes = dict(projection.get("quotes") or {})
        quote = quotes.get(symbol.upper()) or {}
        value = quote.get("last")
        if value is not None:
            return round(float(value), 6)
        for item in projection.get("positions") or []:
            if str(item.get("symbol") or "").upper() == symbol.upper():
                return round(float(((item.get("quote") or {}).get("last")) or 0.0), 6)
        return 0.0

    def _paper_pnl(self, order: PaperOrder, snapshot: PaperPortfolioSnapshot) -> float:
        current_price = self._current_price(order.symbol, snapshot)
        quantity = float(order.paper_quantity_estimate or 0.0)
        if order.side == "SELL":
            return round((float(order.paper_price) - current_price) * quantity, 4)
        return round((current_price - float(order.paper_price)) * quantity, 4)

    def _paper_return_pct(self, order: PaperOrder, snapshot: PaperPortfolioSnapshot) -> float:
        notional = float(order.paper_notional_estimate or 0.0)
        if notional <= 0:
            return 0.0
        return round((self._paper_pnl(order, snapshot) / notional) * 100, 4)

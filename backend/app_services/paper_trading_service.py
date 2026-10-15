from __future__ import annotations

from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.decision_journal_service import DecisionJournalService
from backend.app_services.pre_trade_review_service import PreTradeReviewService
from backend.execution_guard import is_canonical_execution_guard
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    PaperOrder,
    PaperOrderCancelRequest,
    PaperOrderStatus,
    PreTradeReviewStatus,
    PriceSnapshot,
    now_iso,
)


class PaperOrderConflictError(ValueError):
    pass


class PaperTradingService:
    def __init__(
        self,
        repo: WorkbenchRepository,
        audit_service: AuditService,
        pre_trade_review_service: PreTradeReviewService,
        decision_journal_service: DecisionJournalService,
    ) -> None:
        self.repo = repo
        self.audit_service = audit_service
        self.pre_trade_review_service = pre_trade_review_service
        self.decision_journal_service = decision_journal_service

    def create(self, review_id: str, *, source_mode: str = "http") -> PaperOrder:
        review = self.pre_trade_review_service.get(review_id)
        if review.status not in {PreTradeReviewStatus.PASSED, PreTradeReviewStatus.WARNING}:
            raise PaperOrderConflictError("only passed or warning pre-trade reviews can create paper order")
        if not is_canonical_execution_guard(review.execution_guard):
            raise PaperOrderConflictError("unsafe pre-trade review execution guard cannot create paper order")

        quote = PriceSnapshot(**review.quote_snapshot)
        side = self._side(review.delta_weight_pct)
        notional = round(review.portfolio_total_value * abs(review.delta_weight_pct) / 100, 4)
        quantity = round(notional / quote.last, 6) if quote.last > 0 else 0.0
        now = quote.updated_at
        status = PaperOrderStatus.PAPER_FILLED
        note = None
        filled_at = now
        rejected_at = None
        if side == "HOLD":
            status = PaperOrderStatus.PAPER_REJECTED
            note = "delta_weight_pct is zero"
            filled_at = None
            rejected_at = now
        elif quote.last <= 0:
            status = PaperOrderStatus.PAPER_REJECTED
            note = "quote.last must be greater than zero"
            filled_at = None
            rejected_at = now

        order = PaperOrder(
            order_id=f"paper_{uuid4().hex[:12]}",
            review_id=review.review_id,
            source_draft_id=review.source_draft_id,
            status=status,
            symbol=review.symbol,
            side=side,
            target_weight_pct=review.target_weight_pct,
            delta_weight_pct=review.delta_weight_pct,
            paper_price=quote.last,
            paper_price_source=quote.source,
            paper_price_updated_at=quote.updated_at,
            paper_quantity_estimate=quantity,
            paper_notional_estimate=notional,
            quote_degraded=quote.degraded,
            quote_degraded_reason=quote.degraded_reason,
            risk_policy_ref=review.risk_policy_ref,
            execution_guard=dict(review.execution_guard),
            evidence_refs=list(review.evidence_refs),
            source_mode=source_mode,
            filled_at=filled_at,
            rejected_at=rejected_at,
            note=note,
        )
        saved = self.repo.save_paper_order(order)
        self.audit_service.record(
            "paper order created",
            f"{saved.order_id} review={saved.review_id} status={saved.status.value}",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_paper_order(saved)
        return saved

    def list(
        self,
        *,
        review_id: str | None = None,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[PaperOrder]:
        return self.repo.list_paper_orders(
            review_id=review_id,
            draft_id=draft_id,
            symbol=symbol,
            status=status,
            limit=limit,
        )

    def get(self, order_id: str) -> PaperOrder:
        order = self.repo.get_paper_order(order_id)
        if not order:
            raise KeyError(order_id)
        return order

    def cancel(self, order_id: str, payload: PaperOrderCancelRequest) -> PaperOrder:
        order = self.get(order_id)
        if order.status == PaperOrderStatus.PAPER_CANCELLED:
            raise PaperOrderConflictError("paper order is already cancelled")
        order.status = PaperOrderStatus.PAPER_CANCELLED
        order.cancelled_at = order.cancelled_at or now_iso()
        order.note = payload.note or order.note
        saved = self.repo.save_paper_order(order)
        self.audit_service.record(
            "paper order cancelled",
            f"{saved.order_id} review={saved.review_id}",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_paper_order(saved)
        return saved

    def _side(self, delta_weight_pct: float) -> str:
        if delta_weight_pct > 0:
            return "BUY"
        if delta_weight_pct < 0:
            return "SELL"
        return "HOLD"

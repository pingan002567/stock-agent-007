from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.context_builder import ContextBuilder
from backend.app_services.decision_journal_service import DecisionJournalService
from backend.execution_guard import canonical_execution_guard
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    DecisionContext,
    RebalanceDraft,
    RebalanceDraftCreateRequest,
    RebalanceDraftDecisionNoteRequest,
    RebalanceDraftRequest,
    RebalanceDraftStatus,
    model_to_dict,
)


class RebalanceDraftConflictError(ValueError):
    pass


class RebalanceDraftExpiredError(RebalanceDraftConflictError):
    pass


class RebalanceDraftService:
    def __init__(
        self,
        repo: WorkbenchRepository,
        context_builder: ContextBuilder,
        audit_service: AuditService,
        risk_policy_service: RiskPolicyService,
        decision_journal_service: DecisionJournalService,
    ) -> None:
        self.repo = repo
        self.context_builder = context_builder
        self.audit_service = audit_service
        self.risk_policy_service = risk_policy_service
        self.decision_journal_service = decision_journal_service

    def create(
        self,
        payload: RebalanceDraftRequest | RebalanceDraftCreateRequest | dict,
        *,
        source_mode: str = "http",
    ) -> RebalanceDraft:
        if isinstance(payload, dict):
            payload = RebalanceDraftCreateRequest(**payload)
        context = self.context_builder.build_stock_context(payload.symbol)
        policy = self.risk_policy_service.get_active_policy()
        current_weight = round(context.holding.weight_pct, 2)
        target_weight = round(float(payload.target_weight_pct), 2)
        action = "REDUCE" if target_weight < current_weight else "ADD" if target_weight > current_weight else "HOLD"
        valid_until = (_utc_now() + timedelta(hours=policy.rules.draft_valid_hours)).isoformat()
        draft = RebalanceDraft(
            draft_id=f"draft_{uuid4().hex[:12]}",
            decision_id=f"decision_{uuid4().hex[:10]}",
            symbol=context.symbol,
            name=context.name,
            action=action,
            current_weight_pct=current_weight,
            target_weight_pct=target_weight,
            delta_weight_pct=round(target_weight - current_weight, 2),
            conclusion=f"{context.symbol} 调仓草案：{current_weight:.1f}% -> {target_weight:.1f}%",
            reasons=[
                f"当前仓位 {current_weight:.1f}%，目标仓位 {target_weight:.1f}%",
                f"当前风险标签：{context.ai_state.risk_label}",
                "V1 只生成拟单草案，真实交易保持关闭",
            ],
            counter_reasons=[
                "目标仓位基于本地 mock/provider-router 数据，接入真实数据源后需要复核",
                "若价格快速波动，拟单数量和影响需重新计算",
            ],
            evidence_refs=["holding_position", "stock_context", "draft_order_guard:auto_trade_false"],
            valid_until=valid_until,
            validity_source="risk_policy.rules.draft_valid_hours",
            risk_policy_ref=self.risk_policy_service.build_ref(policy),
            source_mode=source_mode,
        )
        draft.output = self._draft_output(draft)
        saved = self.repo.save_rebalance_draft(draft)
        self.audit_service.record(
            "rebalance draft created",
            f"{saved.draft_id} {saved.symbol} target={saved.target_weight_pct:.1f}%",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_draft(saved)
        return saved

    def list(self, *, symbol: str | None = None, status: str | None = None, limit: int = 50) -> list[RebalanceDraft]:
        fetch_limit = None if status is not None else limit
        items = self.repo.list_rebalance_drafts(symbol=symbol, limit=fetch_limit)
        refreshed = [self._expire_if_needed(item) for item in items]
        if status is not None:
            refreshed = [item for item in refreshed if item.status.value == status]
            return refreshed[:limit]
        return refreshed

    def get(self, draft_id: str) -> RebalanceDraft:
        draft = self.repo.get_rebalance_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        return self._expire_if_needed(draft)

    def confirm(self, draft_id: str, payload: RebalanceDraftDecisionNoteRequest) -> RebalanceDraft:
        draft = self.get(draft_id)
        if draft.status == RebalanceDraftStatus.EXPIRED:
            raise RebalanceDraftExpiredError("draft expired; regenerate a new draft before confirming")
        if draft.status != RebalanceDraftStatus.PENDING_USER_CONFIRMATION:
            raise RebalanceDraftConflictError(f"draft is already {draft.status.value}")
        now = _utc_now().isoformat()
        draft.status = RebalanceDraftStatus.CONFIRMED_NO_EXECUTION
        draft.note = payload.note or None
        draft.confirmed_at = now
        draft.updated_at = now
        draft.output = self._draft_output(draft)
        saved = self.repo.save_rebalance_draft(draft)
        self.audit_service.record(
            "rebalance draft confirmed",
            f"{saved.draft_id} {saved.symbol} confirmed_no_execution",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_draft(saved)
        return saved

    def reject(self, draft_id: str, payload: RebalanceDraftDecisionNoteRequest) -> RebalanceDraft:
        draft = self.get(draft_id)
        if draft.status != RebalanceDraftStatus.PENDING_USER_CONFIRMATION:
            raise RebalanceDraftConflictError(f"draft is already {draft.status.value}")
        now = _utc_now().isoformat()
        draft.status = RebalanceDraftStatus.REJECTED
        draft.note = payload.note or None
        draft.rejected_at = now
        draft.updated_at = now
        draft.output = self._draft_output(draft)
        saved = self.repo.save_rebalance_draft(draft)
        self.audit_service.record(
            "rebalance draft rejected",
            f"{saved.draft_id} {saved.symbol} rejected",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_draft(saved)
        return saved

    def expire(self, draft_id: str) -> RebalanceDraft:
        draft = self.get(draft_id)
        return self._expire_if_needed(draft)

    def to_decision_summary(self, draft: RebalanceDraft) -> dict:
        summary = DecisionContext(
            decision_id=draft.decision_id,
            subject={"type": "holding", "symbol": draft.symbol, "name": draft.name},
            skill="rebalance-planner",
            conclusion=draft.conclusion,
            confidence=draft.confidence,
            reasons=list(draft.reasons),
            counter_reasons=list(draft.counter_reasons),
            evidence_refs=list(draft.evidence_refs),
            valid_until=draft.valid_until,
            authority_level=draft.authority_level,
            output=self._draft_output(draft),
        )
        payload = model_to_dict(summary)
        payload["draft_id"] = draft.draft_id
        payload["draft_status"] = draft.status.value
        return payload

    def to_tool_result(self, draft: RebalanceDraft) -> dict:
        return {
            "draft_id": draft.draft_id,
            "draft_status": draft.status.value,
            "auto_trade": draft.auto_trade,
            "draft_order": self._draft_order_payload(draft),
        }

    def _expire_if_needed(self, draft: RebalanceDraft) -> RebalanceDraft:
        if draft.status != RebalanceDraftStatus.PENDING_USER_CONFIRMATION:
            return draft
        if _parse_iso(draft.valid_until) > _utc_now():
            return draft
        now = _utc_now().isoformat()
        draft.status = RebalanceDraftStatus.EXPIRED
        draft.expired_at = now
        draft.updated_at = now
        draft.output = self._draft_output(draft)
        saved = self.repo.save_rebalance_draft(draft)
        self.audit_service.record(
            "rebalance draft expired",
            f"{saved.draft_id} {saved.symbol} expired",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_draft(saved)
        return saved

    def _draft_order_payload(self, draft: RebalanceDraft) -> dict:
        return {
            "draft_id": draft.draft_id,
            "symbol": draft.symbol,
            "action": draft.action,
            "current_weight_pct": draft.current_weight_pct,
            "target_weight_pct": draft.target_weight_pct,
            "delta_weight_pct": draft.delta_weight_pct,
            "status": draft.status.value,
            "auto_trade": draft.auto_trade,
            "note": draft.note,
            "valid_until": draft.valid_until,
            "validity_source": draft.validity_source,
            "risk_policy_ref": model_to_dict(draft.risk_policy_ref) if draft.risk_policy_ref else None,
        }

    def _draft_output(self, draft: RebalanceDraft) -> dict:
        return {
            "draft_order": self._draft_order_payload(draft),
            "execution_guard": canonical_execution_guard(),
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)

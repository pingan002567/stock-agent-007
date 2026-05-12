from __future__ import annotations

from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.decision_journal_service import DecisionJournalService
from backend.app_services.rebalance_draft_service import RebalanceDraftService
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.execution_guard import canonical_execution_guard, extract_execution_guard, is_canonical_execution_guard
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    PreTradeReview,
    PreTradeReviewStatus,
    RebalanceDraft,
    RebalanceDraftStatus,
    RiskPolicy,
    RiskPolicyRef,
    RiskPolicyRules,
    model_to_dict,
)
from backend.stock_domain.catalog import get_stock
from backend.stock_domain.provider_router import provider_router


class PreTradeReviewConflictError(ValueError):
    pass


class PreTradeReviewService:
    def __init__(
        self,
        repo: WorkbenchRepository,
        audit_service: AuditService,
        rebalance_draft_service: RebalanceDraftService,
        risk_policy_service: RiskPolicyService,
        decision_journal_service: DecisionJournalService,
    ) -> None:
        self.repo = repo
        self.audit_service = audit_service
        self.rebalance_draft_service = rebalance_draft_service
        self.risk_policy_service = risk_policy_service
        self.decision_journal_service = decision_journal_service

    def create(
        self,
        draft_id: str | None = None,
        *,
        symbol: str | None = None,
        source_mode: str = "http",
        strict_status: bool = False,
    ) -> PreTradeReview:
        draft = self._resolve_draft(draft_id=draft_id, symbol=symbol)
        if strict_status and draft.status != RebalanceDraftStatus.CONFIRMED_NO_EXECUTION:
            raise PreTradeReviewConflictError(
                f"draft must be confirmed_no_execution before review, current={draft.status.value}"
            )

        holdings = self.repo.list_holdings()
        portfolio_total_value = round(sum(item.market_value for item in holdings), 2)
        quote = provider_router.get_quote(draft.symbol)
        policy, policy_ref, policy_blockers = self._resolve_policy(draft)

        blocker_codes = list(policy_blockers)
        checklist: list[dict] = []

        draft_status_blocked = draft.status != RebalanceDraftStatus.CONFIRMED_NO_EXECUTION
        checklist.append(
            self._check_item(
                code="draft_status_confirmed_no_execution",
                status="blocked" if draft_status_blocked else "passed",
                severity="high" if draft_status_blocked else "low",
                message="拟单必须先由用户显式确认且不能处于 pending/rejected/expired。",
                actual_value=draft.status.value,
                threshold_value=RebalanceDraftStatus.CONFIRMED_NO_EXECUTION.value,
                evidence_refs=["rebalance_draft"],
            )
        )
        if draft_status_blocked:
            blocker_codes.append(f"draft_status_{draft.status.value}")

        raw_execution_guard = self._raw_execution_guard(draft)
        execution_blocked = draft.auto_trade is not False or not self._execution_guard_is_safe(raw_execution_guard)
        checklist.append(
            self._check_item(
                code="execution_guard_safe",
                status="blocked" if execution_blocked else "passed",
                severity="high" if execution_blocked else "low",
                message="执行保护必须显式保持 auto_trade=false，且真实交易继续关闭。",
                actual_value={
                    "draft_auto_trade": draft.auto_trade,
                    "draft_output_execution_guard": raw_execution_guard,
                },
                threshold_value={
                    "draft_auto_trade": False,
                    "auto_trade": False,
                    "place_real_order_enabled": False,
                    "paper_trading": "sandbox_only",
                    "real_order": "blocked",
                },
                evidence_refs=["draft_order_guard:auto_trade_false", "permission_guard:real_order_disabled"],
            )
        )
        if execution_blocked:
            blocker_codes.append("execution_guard_unsafe")
        review_execution_guard = canonical_execution_guard() if not execution_blocked else raw_execution_guard or {}

        effective_rules = policy.rules if policy else None
        checklist.append(
            self._check_item(
                code="risk_policy_ref_match",
                status="blocked" if policy_blockers else "passed",
                severity="high" if policy_blockers else "low",
                message="若草案固化过 risk_policy_ref，则必须与当前同 policy_id/version/updated_at 精确一致。",
                actual_value=model_to_dict(policy_ref) if policy_ref else None,
                threshold_value="exact_match(policy_id, version, updated_at)",
                evidence_refs=["risk_policy", "rebalance_draft"],
            )
        )

        if effective_rules:
            single_position_blocked = draft.target_weight_pct > effective_rules.single_position_max_weight_pct
            checklist.append(
                self._check_item(
                    code="single_position_max_weight_pct",
                    status="blocked" if single_position_blocked else "passed",
                    severity="high" if single_position_blocked else "low",
                    message="目标仓位不得超过单股上限。",
                    actual_value=draft.target_weight_pct,
                    threshold_value=effective_rules.single_position_max_weight_pct,
                    evidence_refs=["rebalance_draft", "risk_policy"],
                )
            )
            if single_position_blocked:
                blocker_codes.append("single_position_max_weight_exceeded")

            projected_sector = self._projected_sector_weight(draft, holdings)
            sector_blocked = projected_sector > effective_rules.sector_max_weight_pct
            checklist.append(
                self._check_item(
                    code="sector_max_weight_pct",
                    status="blocked" if sector_blocked else "passed",
                    severity="high" if sector_blocked else "low",
                    message="投影后板块暴露不得超过风险策略上限。",
                    actual_value=projected_sector,
                    threshold_value=effective_rules.sector_max_weight_pct,
                    evidence_refs=["holding_position", "risk_policy", "stock_catalog"],
                )
            )
            if sector_blocked:
                blocker_codes.append("sector_max_weight_exceeded")

            single_position_warning = draft.target_weight_pct > effective_rules.single_position_warning_weight_pct
            checklist.append(
                self._check_item(
                    code="single_position_warning_weight_pct",
                    status="warning" if single_position_warning else "passed",
                    severity="medium" if single_position_warning else "low",
                    message="目标仓位若超过预警线，需要人工二次确认。",
                    actual_value=draft.target_weight_pct,
                    threshold_value=effective_rules.single_position_warning_weight_pct,
                    evidence_refs=["rebalance_draft", "risk_policy"],
                )
            )

            min_delta_warning = abs(draft.delta_weight_pct) < effective_rules.rebalance_min_delta_pct
            checklist.append(
                self._check_item(
                    code="rebalance_min_delta_pct",
                    status="warning" if min_delta_warning else "passed",
                    severity="medium" if min_delta_warning else "low",
                    message="调仓变动过小，可能不足以形成有效再平衡。",
                    actual_value=abs(draft.delta_weight_pct),
                    threshold_value=effective_rules.rebalance_min_delta_pct,
                    evidence_refs=["rebalance_draft", "risk_policy"],
                )
            )
        else:
            checklist.extend(
                [
                    self._check_item(
                        code="single_position_max_weight_pct",
                        status="blocked",
                        severity="high",
                        message="无法解析有效风险策略，不能完成单股上限校验。",
                        actual_value=draft.target_weight_pct,
                        threshold_value=None,
                        evidence_refs=["risk_policy", "rebalance_draft"],
                    ),
                    self._check_item(
                        code="sector_max_weight_pct",
                        status="blocked",
                        severity="high",
                        message="无法解析有效风险策略，不能完成板块暴露校验。",
                        actual_value=None,
                        threshold_value=None,
                        evidence_refs=["risk_policy", "holding_position"],
                    ),
                ]
            )

        checklist.append(
            self._check_item(
                code="quote_health",
                status="warning" if quote.degraded else "passed",
                severity="medium" if quote.degraded else "low",
                message="行情若已降级，可继续 paper sandbox，但要保留降级来源。",
                actual_value=model_to_dict(quote),
                threshold_value={"degraded": False},
                evidence_refs=["provider_router", "quote_snapshot"],
            )
        )

        deduped_blockers = list(dict.fromkeys(blocker_codes))
        has_warning = any(item["status"] == "warning" for item in checklist)
        status = (
            PreTradeReviewStatus.BLOCKED
            if deduped_blockers
            else PreTradeReviewStatus.WARNING
            if has_warning
            else PreTradeReviewStatus.PASSED
        )
        review = PreTradeReview(
            review_id=f"review_{uuid4().hex[:12]}",
            source_draft_id=draft.draft_id,
            status=status,
            symbol=draft.symbol,
            side=self._side_for_delta(draft.delta_weight_pct),
            current_weight_pct=draft.current_weight_pct,
            target_weight_pct=draft.target_weight_pct,
            delta_weight_pct=draft.delta_weight_pct,
            draft_status_at_review=draft.status.value,
            risk_policy_ref=policy_ref,
            risk_policy_rules_snapshot=model_to_dict(effective_rules) if effective_rules else {},
            quote_snapshot=model_to_dict(quote),
            portfolio_total_value=portfolio_total_value,
            checklist=checklist,
            blocker_codes=deduped_blockers,
            evidence_refs=self._evidence_refs(draft, quote.degraded),
            execution_guard=review_execution_guard,
            degraded=bool(quote.degraded),
            degraded_reason=quote.degraded_reason,
            source_mode=source_mode,
        )
        saved = self.repo.save_pre_trade_review(review)
        self.audit_service.record(
            "pre-trade review created",
            f"{saved.review_id} draft={saved.source_draft_id} status={saved.status.value}",
            AuthorityLevel.A4,
        )
        self.decision_journal_service.upsert_from_review(saved)
        return saved

    def list(
        self,
        *,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[PreTradeReview]:
        return self.repo.list_pre_trade_reviews(draft_id=draft_id, symbol=symbol, status=status, limit=limit)

    def get(self, review_id: str) -> PreTradeReview:
        review = self.repo.get_pre_trade_review(review_id)
        if not review:
            raise KeyError(review_id)
        return review

    def to_tool_result(self, review: PreTradeReview) -> dict:
        return {
            "review_id": review.review_id,
            "draft_id": review.source_draft_id,
            "status": review.status.value,
            "blocker_codes": list(review.blocker_codes),
            "execution_guard": dict(review.execution_guard),
            "degraded": review.degraded,
            "degraded_reason": review.degraded_reason,
        }

    def _resolve_draft(self, *, draft_id: str | None, symbol: str | None) -> RebalanceDraft:
        if draft_id:
            return self.rebalance_draft_service.get(draft_id)
        if symbol:
            items = self.rebalance_draft_service.list(
                symbol=symbol.upper(),
                status=RebalanceDraftStatus.CONFIRMED_NO_EXECUTION.value,
                limit=1,
            )
            if items:
                return items[0]
            fallback = self.rebalance_draft_service.list(symbol=symbol.upper(), limit=1)
            if fallback:
                return fallback[0]
        raise KeyError(draft_id or symbol or "draft")

    def _resolve_policy(self, draft: RebalanceDraft) -> tuple[RiskPolicy | None, RiskPolicyRef | None, list[str]]:
        if not draft.risk_policy_ref:
            policy = self.risk_policy_service.get_active_policy()
            return policy, self.risk_policy_service.build_ref(policy), []
        policy = self.repo.get_risk_policy(draft.risk_policy_ref.policy_id)
        blockers: list[str] = []
        if not policy:
            blockers.append("risk_policy_ref_not_found")
            return None, draft.risk_policy_ref, blockers
        if (
            policy.version != draft.risk_policy_ref.version
            or policy.updated_at != draft.risk_policy_ref.updated_at
            or (policy.policy_id or "") != draft.risk_policy_ref.policy_id
        ):
            blockers.append("risk_policy_ref_mismatch")
        return policy, draft.risk_policy_ref, blockers

    def _raw_execution_guard(self, draft: RebalanceDraft) -> dict | None:
        return extract_execution_guard(draft.output)

    def _execution_guard_is_safe(self, guard: object) -> bool:
        return is_canonical_execution_guard(guard)

    def _projected_sector_weight(self, draft: RebalanceDraft, holdings: list) -> float:
        stock = get_stock(draft.symbol) or {}
        sector = str(stock.get("sector") or "unknown")
        projected = 0.0
        for item in holdings:
            item_sector = str((get_stock(item.symbol) or {}).get("sector") or "unknown")
            if item_sector != sector:
                continue
            projected += draft.target_weight_pct if item.symbol.upper() == draft.symbol.upper() else item.weight_pct
        if projected == 0:
            projected = draft.target_weight_pct
        return round(projected, 2)

    def _side_for_delta(self, delta_weight_pct: float) -> str:
        if delta_weight_pct > 0:
            return "BUY"
        if delta_weight_pct < 0:
            return "SELL"
        return "HOLD"

    def _evidence_refs(self, draft: RebalanceDraft, quote_degraded: bool) -> list[str]:
        refs = [
            "rebalance_draft",
            "holding_position",
            "risk_policy",
            "provider_router",
            "draft_order_guard:auto_trade_false",
        ]
        refs.extend(draft.evidence_refs)
        if quote_degraded:
            refs.append("provider_router:degraded")
        return list(dict.fromkeys(refs))

    def _check_item(
        self,
        *,
        code: str,
        status: str,
        severity: str,
        message: str,
        actual_value: object,
        threshold_value: object,
        evidence_refs: list[str],
    ) -> dict:
        return {
            "code": code,
            "status": status,
            "severity": severity,
            "message": message,
            "actual_value": actual_value,
            "threshold_value": threshold_value,
            "evidence_refs": evidence_refs,
        }

from __future__ import annotations

import re
from typing import Iterable

from backend.app_services.audit_service import AuditService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AuthorityLevel, HoldingPosition, RiskPolicy, RiskPolicyRef, model_to_dict, now_iso
from backend.stock_domain.risk_tools import analyze_portfolio_risk


class RiskPolicyService:
    def __init__(self, repo: WorkbenchRepository, audit_service: AuditService) -> None:
        self.repo = repo
        self.audit_service = audit_service

    def list_policies(self) -> list[RiskPolicy]:
        return self.repo.list_risk_policies()

    def get_policy(self, policy_id: str) -> RiskPolicy:
        policy = self.repo.get_risk_policy(policy_id)
        if not policy:
            raise KeyError(policy_id)
        return policy

    def get_active_policy(self) -> RiskPolicy:
        policy = self.repo.get_active_risk_policy()
        if not policy:
            raise KeyError("active risk policy not found")
        return policy

    def create_policy(self, payload: RiskPolicy) -> RiskPolicy:
        policy_id = payload.policy_id or _slugify(payload.name) or "risk-policy"
        if self.repo.get_risk_policy(policy_id):
            raise ValueError(f"risk policy already exists: {policy_id}")
        saved = self.repo.save_risk_policy(
            payload.model_copy(
                update={
                    "policy_id": policy_id,
                    "is_active": False,
                    "is_default": False,
                    "created_at": payload.created_at,
                    "updated_at": payload.updated_at,
                    "version": max(payload.version, 1),
                }
            )
        )
        self.audit_service.record("risk policy created", saved.policy_id or saved.name, AuthorityLevel.A2)
        return saved

    def update_policy(self, policy_id: str, payload: RiskPolicy) -> RiskPolicy:
        existing = self.get_policy(policy_id)
        updated = payload.model_copy(
            update={
                "policy_id": policy_id,
                "is_active": existing.is_active,
                "is_default": existing.is_default,
                "created_at": existing.created_at,
                "updated_at": now_iso(),
                "version": max(existing.version + 1, payload.version or existing.version + 1),
            }
        )
        saved = self.repo.save_risk_policy(updated)
        self.audit_service.record("risk policy updated", saved.policy_id or saved.name, AuthorityLevel.A2)
        return saved

    def activate_policy(self, policy_id: str) -> RiskPolicy:
        self.get_policy(policy_id)
        activated = self.repo.activate_risk_policy(policy_id, updated_at=now_iso())
        if not activated:
            raise KeyError(policy_id)
        self.audit_service.record("risk policy activated", activated.policy_id or activated.name, AuthorityLevel.A2)
        return activated

    def build_ref(self, policy: RiskPolicy | None = None) -> RiskPolicyRef:
        current = policy or self.get_active_policy()
        return RiskPolicyRef(
            policy_id=current.policy_id or "risk-policy",
            name=current.name,
            version=current.version,
            updated_at=current.updated_at,
        )

    def analyze_portfolio_risk(
        self,
        holdings: Iterable[HoldingPosition],
        *,
        policy: RiskPolicy | None = None,
    ) -> dict:
        current = policy or self.get_active_policy()
        return analyze_portfolio_risk(
            holdings,
            rules=current.rules,
            risk_policy_ref=model_to_dict(self.build_ref(current)),
        )

    def get_monitor_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, float | int]:
        current = policy or self.get_active_policy()
        return {
            "threshold": current.rules.single_position_warning_weight_pct,
            "cooldown_seconds": current.rules.monitor_default_cooldown_seconds,
        }

    def get_strategy_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, float]:
        current = policy or self.get_active_policy()
        return {
            "max_position_weight_pct": current.rules.single_position_max_weight_pct,
            "sector_limit_pct": current.rules.sector_max_weight_pct,
            "rebalance_band_pct": current.rules.rebalance_min_delta_pct,
        }

    def get_rebalance_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, int]:
        current = policy or self.get_active_policy()
        return {"draft_valid_hours": current.rules.draft_valid_hours}

    def settings_summary(self) -> dict:
        active = self.get_active_policy()
        return {
            "active": model_to_dict(active),
            "active_ref": model_to_dict(self.build_ref(active)),
            "count": len(self.list_policies()),
        }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")

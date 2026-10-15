from __future__ import annotations

import re
from typing import Iterable

from backend.app_services.audit_service import AuditService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    HoldingPosition,
    RiskPolicy,
    RiskPolicyRef,
    RiskPolicyRules,
    model_to_dict,
    now_iso,
)
from backend.stock_domain.risk_tools import analyze_portfolio_risk, resolve_effective_rules


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

    def patch_policy(
        self,
        *,
        policy_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        rules_patch: dict | None = None,
        activate: bool = False,
    ) -> RiskPolicy:
        """部分更新风险策略（未传字段保留原值）；policy_id 空则改当前生效策略。"""
        current = self.get_policy(policy_id) if policy_id else self.get_active_policy()
        rules_data = model_to_dict(current.rules)
        patch = dict(rules_patch or {})
        if "capital_tiers" in patch and patch["capital_tiers"] is not None:
            rules_data["capital_tiers"] = patch["capital_tiers"]
        for key, value in patch.items():
            if key == "capital_tiers" or value is None:
                continue
            rules_data[key] = value
        payload = RiskPolicy(
            policy_id=current.policy_id,
            name=(name if name is not None and str(name).strip() else current.name),
            description=current.description if description is None else description,
            is_active=current.is_active,
            is_default=current.is_default,
            rules=RiskPolicyRules(**rules_data),
            version=current.version,
            created_at=current.created_at,
            updated_at=now_iso(),
        )
        saved = self.update_policy(current.policy_id or "risk-policy", payload)
        if activate and not saved.is_active:
            saved = self.activate_policy(saved.policy_id or "risk-policy")
        return saved

    def build_ref(self, policy: RiskPolicy | None = None) -> RiskPolicyRef:
        current = policy or self.get_active_policy()
        return RiskPolicyRef(
            policy_id=current.policy_id or "risk-policy",
            name=current.name,
            version=current.version,
            updated_at=current.updated_at,
        )

    def portfolio_nav(self, holdings: Iterable[HoldingPosition] | None = None) -> float:
        items = list(holdings) if holdings is not None else self.repo.list_holdings()
        return round(sum(float(item.market_value or 0.0) for item in items), 2)

    def analyze_portfolio_risk(
        self,
        holdings: Iterable[HoldingPosition],
        *,
        policy: RiskPolicy | None = None,
    ) -> dict:
        current = policy or self.get_active_policy()
        items = list(holdings)
        return analyze_portfolio_risk(
            items,
            rules=current.rules,
            risk_policy_ref=model_to_dict(self.build_ref(current)),
            portfolio_nav=self.portfolio_nav(items),
        )

    def get_monitor_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, float | int]:
        current = policy or self.get_active_policy()
        effective = resolve_effective_rules(current.rules, self.portfolio_nav())
        return {
            "threshold": effective.single_position_warning_weight_pct,
            "cooldown_seconds": effective.monitor_default_cooldown_seconds,
        }

    def get_strategy_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, float]:
        current = policy or self.get_active_policy()
        effective = resolve_effective_rules(current.rules, self.portfolio_nav())
        return {
            "max_position_weight_pct": effective.single_position_max_weight_pct,
            "sector_limit_pct": effective.sector_max_weight_pct,
            "rebalance_band_pct": effective.rebalance_min_delta_pct,
            "etf_max_weight_pct": effective.etf_max_weight_pct,
            "min_holdings_count": float(effective.min_holdings_count),
            "single_position_max_loss_pct_of_nav": effective.single_position_max_loss_pct_of_nav,
        }

    def get_rebalance_defaults(self, *, policy: RiskPolicy | None = None) -> dict[str, int]:
        current = policy or self.get_active_policy()
        return {"draft_valid_hours": current.rules.draft_valid_hours}

    def settings_summary(self) -> dict:
        active = self.get_active_policy()
        nav = self.portfolio_nav()
        return {
            "active": model_to_dict(active),
            "active_ref": model_to_dict(self.build_ref(active)),
            "effective_rules": model_to_dict(resolve_effective_rules(active.rules, nav)),
            "portfolio_nav": nav,
            "count": len(self.list_policies()),
        }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")

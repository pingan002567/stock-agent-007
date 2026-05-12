from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AuthorityLevel, BacktestRun, StrategySpec
from backend.stock_domain.backtest_tools import evaluate_strategy_backtest


class StrategyService:
    def __init__(
        self,
        repo: WorkbenchRepository,
        audit_service: AuditService,
        risk_policy_service: RiskPolicyService,
    ) -> None:
        self.repo = repo
        self.audit_service = audit_service
        self.risk_policy_service = risk_policy_service

    def list_strategies(self, *, enabled: bool | None = None) -> list[StrategySpec]:
        return self.repo.list_strategy_specs(enabled=enabled)

    def get_strategy(self, strategy_id: str) -> StrategySpec:
        strategy = self.repo.get_strategy_spec(strategy_id)
        if not strategy:
            raise KeyError(strategy_id)
        return strategy

    def create_strategy(self, payload: StrategySpec) -> StrategySpec:
        spec = self._normalize_spec(payload, existing=None)
        if self.repo.get_strategy_spec(spec.strategy_id or ""):
            raise ValueError(f"strategy already exists: {spec.strategy_id}")
        saved = self.repo.save_strategy_spec(spec)
        self.audit("strategy created", saved.strategy_id or saved.name, AuthorityLevel.A2)
        return saved

    def update_strategy(self, strategy_id: str, payload: StrategySpec) -> StrategySpec:
        existing = self.get_strategy(strategy_id)
        spec = self._normalize_spec(payload, existing=existing, forced_id=strategy_id)
        saved = self.repo.save_strategy_spec(spec)
        self.audit("strategy updated", saved.strategy_id or saved.name, AuthorityLevel.A2)
        return saved

    def delete_strategy(self, strategy_id: str) -> bool:
        self.get_strategy(strategy_id)
        deleted = self.repo.delete_strategy_spec(strategy_id)
        if deleted:
            self.audit("strategy deleted", strategy_id, AuthorityLevel.A2)
        return deleted

    def run_backtest(
        self,
        strategy_id: str,
        *,
        period: dict[str, Any] | None = None,
        universe: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> BacktestRun:
        strategy = self.get_strategy(strategy_id)
        holdings = list(self.repo.list_holdings())
        policy = self.risk_policy_service.get_active_policy()
        merged_parameters = {
            **self.risk_policy_service.get_strategy_defaults(policy=policy),
            **strategy.parameters,
            **(parameters or {}),
        }
        result = evaluate_strategy_backtest(
            strategy,
            holdings=holdings,
            period=period,
            universe=universe,
            parameters=merged_parameters,
            risk_policy=policy,
        )
        run = BacktestRun(
            run_id=f"backtest_{uuid4().hex[:10]}",
            strategy_id=strategy.strategy_id or strategy_id,
            strategy_name=strategy.name,
            strategy_type=strategy.strategy_type,
            strategy_snapshot=deepcopy(result["strategy_snapshot"]),
            period=result["period"],
            universe=result["universe"],
            parameters=result["parameters"],
            metrics=result["metrics"],
            signals=result["signals"],
            risk_summary=result["risk_summary"],
            candidate_actions=result["candidate_actions"],
            evidence_refs=list(dict.fromkeys([*result["evidence_refs"], "backtest_run"])),
            risk_policy_ref=self.risk_policy_service.build_ref(policy),
            execution_guard=result["execution_guard"],
            degraded=result["degraded"],
            degraded_reason=result["degraded_reason"],
        )
        saved = self.repo.save_backtest_run(run)
        self.audit("strategy backtest recorded", f"{saved.strategy_id} -> {saved.run_id}", AuthorityLevel.A3)
        return saved

    def list_backtests(self, strategy_id: str, *, limit: int = 20) -> list[BacktestRun]:
        return self.repo.list_backtest_runs(strategy_id=strategy_id, limit=limit)

    def get_backtest(self, run_id: str) -> BacktestRun:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def audit(self, action: str, detail: str, authority_level: AuthorityLevel = AuthorityLevel.A1):
        return self.audit_service.record(action, detail, authority_level)

    def _normalize_spec(
        self,
        payload: StrategySpec,
        *,
        existing: StrategySpec | None,
        forced_id: str | None = None,
    ) -> StrategySpec:
        strategy_id = forced_id or payload.strategy_id or _slugify(payload.name) or payload.strategy_type.replace("_", "-")
        if existing:
            created_at = existing.created_at
            version = max(existing.version + 1, payload.version or existing.version)
        else:
            created_at = payload.created_at
            version = max(payload.version, 1)
        return payload.model_copy(
            update={
                "strategy_id": strategy_id,
                "universe": [symbol.upper() for symbol in payload.universe],
                "parameters": payload.parameters,
                "tags": payload.tags,
                "created_at": created_at,
                "updated_at": payload.updated_at,
                "version": version,
            }
        )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")

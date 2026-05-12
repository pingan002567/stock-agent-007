from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    AuthorityLevel,
    PaperOrder,
    PaperOrderStatus,
    PaperPortfolioBaseline,
    PaperPortfolioBaselinePosition,
    PaperPortfolioPosition,
    PaperPortfolioProjection,
    PaperPortfolioSnapshot,
    PaperPortfolioWarning,
    RiskPolicyRef,
    model_to_dict,
    now_iso,
)
from backend.stock_domain.provider_router import provider_router


BASELINE_CONFIG_KEY = "paper_portfolio_baseline"


@dataclass
class _ProjectedPosition:
    symbol: str
    name: str
    quantity: float
    cost_basis: float
    baseline_quantity: float
    baseline_price: float
    baseline_market_value: float
    baseline_cost_basis: float
    last_order_risk_policy_ref: RiskPolicyRef | None = None


class PaperPortfolioService:
    def __init__(self, repo: WorkbenchRepository, audit_service: AuditService) -> None:
        self.repo = repo
        self.audit_service = audit_service

    def get_baseline(self) -> PaperPortfolioBaseline:
        payload = self.repo.get_config(BASELINE_CONFIG_KEY)
        if payload:
            return PaperPortfolioBaseline(**payload)
        return self._create_baseline()

    def get_projection(self) -> PaperPortfolioProjection:
        baseline = self.get_baseline()
        positions = self._seed_positions(baseline)
        warnings: list[PaperPortfolioWarning] = []
        risk_refs: list[RiskPolicyRef] = []
        latest_risk_policy_ref: RiskPolicyRef | None = None
        cash = float(baseline.initial_cash)
        effective_orders = self._effective_orders()

        for order in effective_orders:
            symbol = order.symbol.upper()
            state = positions.setdefault(
                symbol,
                _ProjectedPosition(
                    symbol=symbol,
                    name=self._resolve_position_name(symbol),
                    quantity=0.0,
                    cost_basis=0.0,
                    baseline_quantity=0.0,
                    baseline_price=0.0,
                    baseline_market_value=0.0,
                    baseline_cost_basis=0.0,
                ),
            )
            if order.risk_policy_ref:
                state.last_order_risk_policy_ref = order.risk_policy_ref
                latest_risk_policy_ref = order.risk_policy_ref
                if not any(self._same_risk_ref(order.risk_policy_ref, item) for item in risk_refs):
                    risk_refs.append(order.risk_policy_ref)
            quantity = max(float(order.paper_quantity_estimate), 0.0)
            notional = max(float(order.paper_notional_estimate), 0.0)
            if order.side == "BUY":
                state.quantity += quantity
                state.cost_basis += notional
                cash -= notional
                continue
            if order.side != "SELL":
                continue
            old_qty = max(state.quantity, 0.0)
            sell_qty = min(quantity, old_qty)
            if quantity > old_qty:
                warnings.append(
                    PaperPortfolioWarning(
                        code="sell_clamped_no_short",
                        message=f"SELL quantity {quantity} exceeded long position {old_qty}; clamped to avoid short.",
                        symbol=symbol,
                        order_id=order.order_id,
                    )
                )
            avg_cost = state.cost_basis / old_qty if old_qty > 0 else 0.0
            state.quantity = max(old_qty - sell_qty, 0.0)
            state.cost_basis = max(state.cost_basis - avg_cost * sell_qty, 0.0)
            cash += sell_qty * float(order.paper_price)

        projected_positions: list[PaperPortfolioPosition] = []
        quotes: dict[str, dict[str, Any]] = {}
        degraded = False
        market_value = 0.0

        for state in positions.values():
            if state.quantity <= 0:
                continue
            quote = provider_router.get_quote(state.symbol)
            if quote is None:
                quote_payload = {"symbol": state.symbol, "last": 0.0, "change_pct": 0.0, "degraded": True, "degraded_reason": "quote unavailable"}
                degraded = True
            else:
                quote_payload = model_to_dict(quote)
                if quote.degraded:
                    degraded = True
            quotes[state.symbol] = quote_payload
            last_price = float(quote_payload.get("last", 0) or 0)
            position_market_value = round(state.quantity * last_price, 4)
            market_value += position_market_value
            projected_positions.append(
                PaperPortfolioPosition(
                    symbol=state.symbol,
                    name=state.name,
                    quantity=round(state.quantity, 6),
                    cost_basis=round(state.cost_basis, 4),
                    avg_cost=round(state.cost_basis / state.quantity, 6) if state.quantity > 0 else 0.0,
                    baseline_quantity=round(state.baseline_quantity, 6),
                    baseline_price=round(state.baseline_price, 6),
                    baseline_market_value=round(state.baseline_market_value, 4),
                    baseline_cost_basis=round(state.baseline_cost_basis, 4),
                    market_value=position_market_value,
                    pnl=round(position_market_value - state.cost_basis, 4),
                    weight_pct=0.0,
                    quote=quote_payload,
                    last_order_risk_policy_ref=state.last_order_risk_policy_ref,
                )
            )

        equity = round(cash + market_value, 4)
        for position in projected_positions:
            position.weight_pct = round((position.market_value / equity) * 100, 4) if equity else 0.0
        projected_positions.sort(key=lambda item: (-item.market_value, item.symbol))
        market_value = round(market_value, 4)
        cash = round(cash, 4)
        pnl = round(equity - baseline.initial_nav - baseline.initial_cash, 4)

        return PaperPortfolioProjection(
            baseline_id=baseline.baseline_id,
            as_of=now_iso(),
            degraded=degraded,
            initial_nav=round(baseline.initial_nav, 4),
            initial_cash=round(baseline.initial_cash, 4),
            market_value=market_value,
            cash_estimate=cash,
            equity_estimate=equity,
            pnl_estimate=pnl,
            order_count=len(effective_orders),
            warning_count=len(warnings),
            positions=projected_positions,
            warnings=warnings,
            quotes=quotes,
            latest_risk_policy_ref=latest_risk_policy_ref,
            risk_policy_refs=risk_refs,
        )

    def get_summary(self, projection: PaperPortfolioProjection | None = None) -> dict[str, Any]:
        baseline = self.get_baseline()
        projection = projection or self.get_projection()
        return {
            "baseline_id": baseline.baseline_id,
            "baseline_created_at": baseline.created_at,
            "positions": len(projection.positions),
            "order_count": projection.order_count,
            "warning_count": projection.warning_count,
            "degraded": projection.degraded,
            "initial_nav": projection.initial_nav,
            "initial_cash": projection.initial_cash,
            "market_value": projection.market_value,
            "cash_estimate": projection.cash_estimate,
            "equity_estimate": projection.equity_estimate,
            "pnl_estimate": projection.pnl_estimate,
            "latest_risk_policy_ref": model_to_dict(projection.latest_risk_policy_ref)
            if projection.latest_risk_policy_ref
            else None,
        }

    def get_performance(self) -> dict[str, Any]:
        baseline = self.get_baseline()
        projection = self.get_projection()
        baseline_equity = round(baseline.initial_nav + baseline.initial_cash, 4)
        latest_snapshot = next(
            iter(self.repo.list_paper_portfolio_snapshots(baseline_id=baseline.baseline_id, limit=1)),
            None,
        )
        latest_snapshot_delta = None
        if latest_snapshot:
            latest_snapshot_delta = {
                "snapshot_id": latest_snapshot.snapshot_id,
                "snapshot_as_of": latest_snapshot.as_of,
                "equity_delta": round(projection.equity_estimate - latest_snapshot.equity_estimate, 4),
                "pnl_delta": round(projection.pnl_estimate - latest_snapshot.pnl_estimate, 4),
                "market_value_delta": round(projection.market_value - latest_snapshot.market_value, 4),
                "cash_delta": round(projection.cash_estimate - latest_snapshot.cash_estimate, 4),
            }
        return {
            "baseline_id": baseline.baseline_id,
            "as_of": projection.as_of,
            "degraded": projection.degraded,
            "latest_risk_policy_ref": model_to_dict(projection.latest_risk_policy_ref)
            if projection.latest_risk_policy_ref
            else None,
            "risk_policy_refs": [model_to_dict(item) for item in projection.risk_policy_refs],
            "since_baseline": {
                "initial_equity": baseline_equity,
                "current_equity": projection.equity_estimate,
                "market_value": projection.market_value,
                "cash_estimate": projection.cash_estimate,
                "pnl_estimate": projection.pnl_estimate,
                "return_pct": round((projection.pnl_estimate / baseline_equity) * 100, 4) if baseline_equity else 0.0,
            },
            "latest_snapshot_delta": latest_snapshot_delta,
            "quotes": projection.quotes,
            "warnings": [model_to_dict(item) for item in projection.warnings],
        }

    def create_snapshot(self, *, source_mode: str = "http") -> PaperPortfolioSnapshot:
        projection = self.get_projection()
        snapshot = PaperPortfolioSnapshot(
            snapshot_id=f"paper_snapshot_{uuid4().hex[:12]}",
            baseline_id=projection.baseline_id,
            as_of=projection.as_of,
            degraded=projection.degraded,
            market_value=projection.market_value,
            cash_estimate=projection.cash_estimate,
            equity_estimate=projection.equity_estimate,
            pnl_estimate=projection.pnl_estimate,
            payload=model_to_dict(projection),
        )
        saved = self.repo.save_paper_portfolio_snapshot(snapshot)
        self.audit_service.record(
            "paper portfolio snapshot created",
            f"{saved.snapshot_id} baseline={saved.baseline_id} degraded={saved.degraded} source_mode={source_mode}",
            AuthorityLevel.A3,
        )
        return saved

    def list_snapshots(self, *, limit: int = 50) -> list[PaperPortfolioSnapshot]:
        baseline = self.get_baseline()
        return self.repo.list_paper_portfolio_snapshots(baseline_id=baseline.baseline_id, limit=limit)

    def get_snapshot(self, snapshot_id: str) -> PaperPortfolioSnapshot:
        snapshot = self.repo.get_paper_portfolio_snapshot(snapshot_id)
        if not snapshot:
            raise KeyError(snapshot_id)
        return snapshot

    def _create_baseline(self) -> PaperPortfolioBaseline:
        holdings = self.repo.list_holdings()
        positions = []
        initial_nav = 0.0
        for item in holdings:
            quantity = max(float(item.quantity), 0.0)
            market_value = round(float(item.market_value), 4)
            baseline_price = round(market_value / quantity, 6) if quantity > 0 else 0.0
            positions.append(
                PaperPortfolioBaselinePosition(
                    symbol=item.symbol.upper(),
                    name=item.name,
                    quantity=quantity,
                    baseline_price=baseline_price,
                    baseline_market_value=market_value,
                    baseline_cost_basis=market_value,
                )
            )
            initial_nav += market_value
        baseline = PaperPortfolioBaseline(
            baseline_id=f"baseline_{uuid4().hex[:12]}",
            initial_nav=round(initial_nav, 4),
            initial_cash=0.0,
            positions=positions,
        )
        self.repo.set_config(BASELINE_CONFIG_KEY, model_to_dict(baseline))
        return baseline

    def _seed_positions(self, baseline: PaperPortfolioBaseline) -> dict[str, _ProjectedPosition]:
        seeded: dict[str, _ProjectedPosition] = {}
        for item in baseline.positions:
            seeded[item.symbol.upper()] = _ProjectedPosition(
                symbol=item.symbol.upper(),
                name=item.name,
                quantity=float(item.quantity),
                cost_basis=float(item.baseline_cost_basis),
                baseline_quantity=float(item.quantity),
                baseline_price=float(item.baseline_price),
                baseline_market_value=float(item.baseline_market_value),
                baseline_cost_basis=float(item.baseline_cost_basis),
            )
        return seeded

    def _effective_orders(self) -> list[PaperOrder]:
        items = [
            item
            for item in self.repo.list_paper_orders(limit=None)
            if item.status == PaperOrderStatus.PAPER_FILLED
        ]
        items.sort(key=lambda item: (item.filled_at or "", item.created_at, item.order_id))
        return items

    def _resolve_position_name(self, symbol: str) -> str:
        match = next((item.name for item in self.repo.list_holdings() if item.symbol.upper() == symbol.upper()), None)
        return match or symbol.upper()

    def _same_risk_ref(self, left: RiskPolicyRef, right: RiskPolicyRef) -> bool:
        return (
            left.policy_id == right.policy_id
            and left.version == right.version
            and left.updated_at == right.updated_at
        )

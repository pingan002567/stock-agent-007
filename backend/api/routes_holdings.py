from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from pydantic import BaseModel, Field

from backend.schemas import HoldingPosition, RebalanceDraftRequest, model_to_dict
from backend.stock_domain.catalog import get_stock
from backend.stock_domain import fx as fx_service
from backend.stock_domain.portfolio_tools import (
    holding_currency,
    mark_to_market,
    read_available_cash,
    summarize_portfolio,
    to_cny_amount,
    write_available_cash,
)

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


class AvailableCashUpdate(BaseModel):
    amount: float | None = Field(default=None, description="可用资金；null 表示未记录")


def _fx_rates() -> tuple[dict | None, dict]:
    """当日汇率（按日缓存）。返回 (折算系数, 原始 payload)。"""
    payload = fx_service.get_rates()
    return fx_service.rates_for_conversion(payload), payload


def _portfolio_summary(services: AppServices, holdings: list[HoldingPosition]) -> dict:
    rates, payload = _fx_rates()
    return summarize_portfolio(
        holdings,
        available_cash=read_available_cash(services.repo),
        rates=rates,
        fx=payload,
    )


def _presented_holdings(services: AppServices) -> tuple[list[dict], list[HoldingPosition], int]:
    """Attach a quote and compute market value / unrealized P&L for the response."""
    from backend.stock_domain.provider_router import provider_router

    rates, _fx_payload = _fx_rates()
    items: list[dict] = []
    valued: list[HoldingPosition] = []
    degraded_count = 0
    for item in services.repo.list_holdings():
        d = model_to_dict(item)
        stock = get_stock(item.symbol)
        d["market"] = str(stock["market"]) if stock else ""
        last = None
        try:
            quote = provider_router.get_quote(item.symbol)
            coverage = quote.coverage if isinstance(quote.coverage, dict) else {}
            last = quote.last if quote.last else None
            d["quote"] = {
                "last": last,
                "change_pct": None if last is None else quote.change_pct,
                "updated_at": quote.updated_at,
                "degraded": bool(quote.degraded) or last is None,
                "degraded_reason": quote.degraded_reason,
                "stale": bool(coverage.get("stale")),
                "from_cache": bool(coverage.get("from_cache")),
                "channel": "mode_b",
            }
            if d["quote"]["degraded"]:
                degraded_count += 1
        except Exception as exc:
            d["quote"] = {
                "last": None,
                "change_pct": None,
                "degraded": True,
                "degraded_reason": str(exc)[:160],
                "channel": "mode_b",
            }
            degraded_count += 1
        native, pnl_amount, pnl_pct = mark_to_market(item, None if d["quote"]["degraded"] else last)
        currency = holding_currency(item)
        d["currency"] = currency
        # 原币市值（真相）；折算值只在能拿到汇率时给，拿不到就是 None → 前端显示「—」
        d["market_value_native"] = native
        d["market_value"] = to_cny_amount(native, currency, rates)
        d["pnl_amount"] = pnl_amount       # 价格损益，原币口径，不受汇率影响
        d["pnl_pct"] = pnl_pct
        valued.append(item.model_copy(update={"market_value": native, "pnl_pct": pnl_pct, "currency": currency}))
        items.append(d)
    return items, valued, degraded_count


@router.get("")
def list_holdings(request: Request, services: AppServices = Depends(get_services)):
    """Holdings list (Mode B). Attach quote cache status so UI can show degraded, not blank."""
    items, valued, degraded_count = _presented_holdings(services)
    return {
        "summary": _portfolio_summary(services, valued),
        "items": items,
        "demo": services.repo.is_demo_portfolio(),
        "quotes_degraded_count": degraded_count,
        "quotes_total": len(items),
        "channel": "mode_b",
        "fx": _fx_rates()[1],
    }


@router.post("/available-cash")
def set_available_cash(payload: AvailableCashUpdate, request: Request, services: AppServices = Depends(get_services)):
    try:
        amount = write_available_cash(services.repo, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _items, valued, _degraded = _presented_holdings(services)
    services.audit_service.record(
        "holdings available cash updated",
        "cleared" if amount is None else f"amount={amount}",
    )
    return {"available_cash": amount, "summary": _portfolio_summary(services, valued)}


@router.post("/import-preview")
def import_preview(items: List[HoldingPosition]):
    return {"valid": True, "count": len(items), "items": [model_to_dict(item) for item in items]}


@router.post("/import-confirm")
def import_confirm(items: List[HoldingPosition], request: Request, services: AppServices = Depends(get_services)):
    saved = [services.repo.upsert_holding(item) for item in items]
    services.repo.mark_demo_portfolio_real()
    services.audit_service.record("holdings import confirmed", f"count={len(saved)}")
    return {"imported": len(saved), "items": [model_to_dict(item) for item in saved]}


@router.post("/clear-demo")
def clear_demo_holdings(request: Request, services: AppServices = Depends(get_services)):
    if not services.repo.is_demo_portfolio():
        return {"ok": True, "demo": False, "removed": []}
    result = services.repo.clear_demo_portfolio()
    services.audit_service.record("demo holdings cleared", f"removed={len(result['removed'])}")
    return {"ok": True, **result}


@router.get("/risk")
def holdings_risk(request: Request, services: AppServices = Depends(get_services)):
    risk = services.risk_policy_service.analyze_portfolio_risk(services.repo.list_holdings())
    services.audit_service.record("holdings risk review", risk["decision"])
    return risk


@router.post("/rebalance-draft")
def rebalance_draft(payload: RebalanceDraftRequest, request: Request, services: AppServices = Depends(get_services)):
    draft = services.rebalance_draft_service.create(payload, source_mode="http")
    return services.rebalance_draft_service.to_decision_summary(draft)

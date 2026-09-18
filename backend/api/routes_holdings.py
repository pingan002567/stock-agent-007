from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import HoldingPosition, RebalanceDraftRequest, model_to_dict
from backend.stock_domain.catalog import get_stock
from backend.stock_domain.portfolio_tools import summarize_portfolio

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


@router.get("")
def list_holdings(request: Request, services: AppServices = Depends(get_services)):
    """Holdings list (Mode B). Attach quote cache status so UI can show degraded, not blank."""
    from backend.stock_domain.provider_router import provider_router

    holdings = services.repo.list_holdings()
    items = []
    degraded_count = 0
    for item in holdings:
        d = model_to_dict(item)
        stock = get_stock(item.symbol)
        d["market"] = str(stock["market"]) if stock else ""
        try:
            quote = provider_router.get_quote(item.symbol)
            coverage = quote.coverage if isinstance(quote.coverage, dict) else {}
            d["quote"] = {
                "last": quote.last if quote.last else None,
                "change_pct": quote.change_pct,
                "updated_at": quote.updated_at,
                "degraded": bool(quote.degraded),
                "degraded_reason": quote.degraded_reason,
                "stale": bool(coverage.get("stale")),
                "from_cache": bool(coverage.get("from_cache")),
                "channel": "mode_b",
            }
            if quote.degraded or d["quote"]["last"] is None:
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
        items.append(d)
    return {
        "summary": summarize_portfolio(holdings),
        "items": items,
        "demo": services.repo.is_demo_portfolio(),
        "quotes_degraded_count": degraded_count,
        "quotes_total": len(items),
        "channel": "mode_b",
    }


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

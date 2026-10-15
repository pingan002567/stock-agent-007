from __future__ import annotations

from fastapi import APIRouter

from backend.stock_domain.provider_router import provider_router

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/review")
def market_review():
    return provider_router.get_market_review()


@router.get("/sectors")
def market_sectors():
    return provider_router.get_sectors()


@router.get("/timeline")
def market_timeline():
    items = provider_router.get_market_timeline()
    return {"items": items}

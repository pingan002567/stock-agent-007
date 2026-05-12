from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import model_to_dict
from backend.stock_domain.portfolio_tools import summarize_portfolio
from backend.stock_domain.provider_router import provider_router

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
def get_overview(request: Request, services: AppServices = Depends(get_services)):
    watchlist = services.repo.list_watchlist()
    holdings = services.repo.list_holdings()
    focus_symbol = "AAPL"
    focus_context = services.context_builder.build_stock_context(focus_symbol)
    monitor_events = services.monitor_service.list_events(limit=5)
    return {
        "watchlist": [model_to_dict(item) for item in watchlist[:5]],
        "holdings": [model_to_dict(item) for item in holdings[:5]],
        "portfolio_summary": summarize_portfolio(holdings),
        "focus_stock": model_to_dict(focus_context),
        "market_review": provider_router.get_market_review(),
        "sector_summary": provider_router.get_sectors(),
        "monitor_summary": services.monitor_service.build_monitor_summary(),
        "tasks": [model_to_dict(item) for item in services.repo.list_tasks()[:5]],
        "audit": [model_to_dict(item) for item in services.repo.list_audit(5)],
    }

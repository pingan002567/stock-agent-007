from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import HoldingPosition, Report, model_to_dict
from backend.stock_domain.portfolio_tools import mark_to_market, read_available_cash, summarize_portfolio
from backend.stock_domain.provider_router import provider_router

router = APIRouter(prefix="/api", tags=["overview"])


def _holding_card(item: HoldingPosition) -> tuple[dict, HoldingPosition]:
    """Position plus a quote snapshot so the overview table can show day change."""
    from backend.stock_domain.catalog import get_stock

    card = model_to_dict(item)
    stock = get_stock(item.symbol)
    card["market"] = str(stock["market"]) if stock else ""
    last = None
    degraded = True
    try:
        quote = provider_router.get_quote(item.symbol)
        last = quote.last if quote.last else None
        degraded = bool(quote.degraded) or last is None
        card["quote"] = {
            "last": last,
            "change_pct": None if last is None else quote.change_pct,
            "degraded": degraded,
        }
    except Exception as exc:
        card["quote"] = {
            "last": None,
            "change_pct": None,
            "degraded": True,
            "degraded_reason": str(exc)[:160],
        }
    market_value, pnl_amount, pnl_pct = mark_to_market(item, None if degraded else last)
    card["market_value"] = market_value
    card["pnl_amount"] = pnl_amount
    card["pnl_pct"] = pnl_pct
    return card, item.model_copy(update={"market_value": market_value, "pnl_pct": pnl_pct})


def _briefing_card(briefing: Report | None) -> dict | None:
    if briefing is None:
        return None
    payload = briefing.payload or {}
    return {
        "report_id": briefing.report_id,
        "title": briefing.title,
        "conclusion": briefing.conclusion,
        "created_at": briefing.created_at,
        "quality_status": briefing.quality_status,
        "session": payload.get("session"),
        "exception_count": len(payload.get("exceptions") or []),
        "degraded": briefing.degraded,
        "auto_trade": False,
    }


@router.get("/overview")
def get_overview(request: Request, services: AppServices = Depends(get_services)):
    watchlist = services.repo.list_watchlist()
    holdings = services.repo.list_holdings()
    holding_cards: list[dict] = []
    valued: list[HoldingPosition] = []
    for item in holdings[:5]:
        card, marked = _holding_card(item)
        holding_cards.append(card)
        valued.append(marked)
    valued.extend(holdings[5:])
    focus_symbol = "AAPL"
    focus_context = services.context_builder.build_stock_context(focus_symbol)
    briefing = services.report_service.latest_ops_briefing()
    discovery = services.report_service.latest_discovery_briefing()
    inbox_summary = services.review_inbox_service.summarize()
    return {
        "watchlist": [model_to_dict(item) for item in watchlist[:5]],
        "holdings": holding_cards,
        "portfolio_summary": summarize_portfolio(
            valued, available_cash=read_available_cash(services.repo)
        ),
        "focus_stock": model_to_dict(focus_context),
        "market_review": provider_router.get_market_review(),
        "sector_summary": provider_router.get_sectors(),
        "monitor_summary": services.monitor_service.build_monitor_summary(),
        "tasks": [model_to_dict(item) for item in services.repo.list_tasks()[:5]],
        "audit": [model_to_dict(item) for item in services.repo.list_audit(5)],
        "latest_ops_briefing": _briefing_card(briefing),
        "latest_discovery_briefing": _briefing_card(discovery),
        "inbox_summary": model_to_dict(inbox_summary),
    }

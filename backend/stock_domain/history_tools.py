from __future__ import annotations

from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.series_order import sort_history_items


def get_daily_history(symbol: str, days: int = 30) -> dict:
    payload = provider_router.get_history(symbol, days)
    items = payload.get("items")
    if isinstance(items, list):
        payload["items"] = sort_history_items(items)
    return payload

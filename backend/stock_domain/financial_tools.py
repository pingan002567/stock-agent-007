from __future__ import annotations

from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.series_order import sort_financial_items


def get_stock_financial(symbol: str) -> dict:
    payload = provider_router.get_financial(symbol)
    items = payload.get("items")
    if isinstance(items, list):
        payload["items"] = sort_financial_items(items)
    return payload

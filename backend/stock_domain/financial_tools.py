from __future__ import annotations

from backend.stock_domain.provider_router import provider_router


def get_stock_financial(symbol: str) -> dict:
    return provider_router.get_financial(symbol)

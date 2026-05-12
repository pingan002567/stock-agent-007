from __future__ import annotations

from backend.stock_domain.provider_router import provider_router


def get_daily_history(symbol: str, days: int = 30) -> dict:
    return provider_router.get_history(symbol, days)

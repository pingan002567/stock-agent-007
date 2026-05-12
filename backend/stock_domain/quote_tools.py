from __future__ import annotations

from backend.schemas import PriceSnapshot, model_to_dict
from backend.stock_domain.catalog import normalize_symbol
from backend.stock_domain.provider_router import provider_router


def get_realtime_quote(symbol: str) -> PriceSnapshot:
    return provider_router.get_quote(symbol)


def get_quote_card(symbol: str) -> dict:
    return {"symbol": normalize_symbol(symbol), "price": model_to_dict(get_realtime_quote(symbol))}

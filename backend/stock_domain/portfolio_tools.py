from __future__ import annotations

from typing import Iterable, List

from backend.schemas import HoldingPosition


def summarize_portfolio(holdings: Iterable[HoldingPosition]) -> dict:
    items: List[HoldingPosition] = list(holdings)
    total_value = sum(item.market_value for item in items)
    max_weight = max((item.weight_pct for item in items), default=0)
    return {
        "total_value": total_value,
        "positions": len(items),
        "max_weight_pct": max_weight,
        "cash_pct": 9.8,
        "source": "local_sqlite",
    }

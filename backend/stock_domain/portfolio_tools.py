from __future__ import annotations

from typing import Any, Iterable, List

from backend.schemas import HoldingPosition

HOLDINGS_CASH_KEY = "holdings_available_cash"


def read_available_cash(repo: Any) -> float | None:
    raw = repo.get_config(HOLDINGS_CASH_KEY, {})
    amount = raw.get("amount") if isinstance(raw, dict) else None
    if amount is None or amount == "":
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return round(value, 2)


def write_available_cash(repo: Any, amount: float | None) -> float | None:
    if amount is None:
        repo.set_config(HOLDINGS_CASH_KEY, {"amount": None})
        return None
    value = round(float(amount), 2)
    if value < 0:
        raise ValueError("可用资金不能为负")
    repo.set_config(HOLDINGS_CASH_KEY, {"amount": value})
    return value


def mark_to_market(
    item: HoldingPosition,
    last: float | None,
) -> tuple[float, float | None, float | None]:
    """市值、浮动盈亏金额、盈亏比例。

    有现价时市值 = 现价 × 数量，否则沿用已存市值。
    成本是每股成本价；缺成本时盈亏保持为空。
    """
    qty = float(item.quantity or 0)
    market_value = float(item.market_value or 0)
    priced = last is not None and float(last) > 0 and qty > 0
    if priced:
        market_value = round(float(last) * qty, 2)
    cost = item.cost
    if cost is None or qty <= 0 or float(cost) <= 0:
        return round(market_value, 2), None, item.pnl_pct
    basis = float(cost) * qty
    # 没有现价、市值又只是「数量 × 成本」时，盈亏还没算出来，保持空。
    if not priced and abs(market_value - basis) < 0.05:
        return round(market_value, 2), None, None
    pnl_amount = round(market_value - basis, 2)
    pnl_pct = round(pnl_amount / basis * 100, 2) if basis else None
    return round(market_value, 2), pnl_amount, pnl_pct


def summarize_portfolio(
    holdings: Iterable[HoldingPosition],
    *,
    available_cash: float | None = None,
) -> dict:
    items: List[HoldingPosition] = list(holdings)
    market_value = round(sum(float(item.market_value or 0) for item in items), 2)
    max_weight = max((item.weight_pct for item in items), default=0)
    cash = None if available_cash is None else round(float(available_cash), 2)
    total_value = round(market_value + (cash or 0), 2)
    if cash is None:
        cash_pct = None
    elif total_value <= 0:
        cash_pct = 0.0
    else:
        cash_pct = round(cash / total_value * 100, 2)
    return {
        "market_value": market_value,
        "total_value": total_value,
        "positions": len(items),
        "max_weight_pct": max_weight,
        "available_cash": cash,
        "cash_pct": cash_pct,
        "source": "local_sqlite",
    }

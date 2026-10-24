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


#: market → 该市场的原币币种
_MARKET_CURRENCY = {"CN": "CNY", "HK": "HKD", "US": "USD", "CRYPTO": "USDT"}


def holding_currency(item: HoldingPosition) -> str:
    """持仓的原币币种：显式设置的优先，否则按 market 推断，最后退回 CNY。"""
    explicit = str(getattr(item, "currency", "") or "").strip().upper()
    if explicit:
        return explicit
    try:
        from backend.stock_domain.catalog import get_stock

        stock = get_stock(item.symbol)
        market = str((stock or {}).get("market") or "").upper()
        if market in _MARKET_CURRENCY:
            return _MARKET_CURRENCY[market]
    except Exception:  # noqa: BLE001 - 目录不可用不能挡住持仓展示
        pass
    return "CNY"


def to_cny_amount(
    amount: float,
    currency: str,
    rates: dict[str, float] | None,
) -> float | None:
    """原币金额 → 人民币；未拿到汇率返回 None（**不退化、不按 1:1 硬算**）。"""
    if rates is None:
        return None
    rate = rates.get(str(currency or "CNY").upper())
    if rate is None:
        return None
    return round(float(amount or 0) * rate, 2)


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
    rates: dict[str, float] | None = None,
    fx: dict[str, Any] | None = None,
) -> dict:
    """组合汇总：**分币种小计（主）+ 折合人民币总额（辅，只作分母）**。

    `rates` 来自 `stock_domain.fx.rates_for_conversion()`：
    - 有汇率 → `market_value` / `total_value` / `weights` 都是人民币口径
    - 无汇率 → 这三个是 None（**不按 1:1 硬算**），但 `by_currency` 的原币小计照常
    """
    items: List[HoldingPosition] = list(holdings)

    # ── 分币种小计（原币，零依赖） ──
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        ccy = holding_currency(item)
        native = round(float(item.market_value or 0), 2)
        bucket = buckets.setdefault(
            ccy, {"currency": ccy, "native": 0.0, "cny": 0.0, "count": 0, "converted": True}
        )
        bucket["native"] = round(bucket["native"] + native, 2)
        bucket["count"] += 1
        cny = to_cny_amount(native, ccy, rates)
        if cny is None:
            bucket["converted"] = False
        else:
            bucket["cny"] = round(bucket["cny"] + cny, 2)

    cash = None if available_cash is None else round(float(available_cash), 2)
    by_currency = [
        {
            "currency": b["currency"],
            "native": b["native"],
            "cny": b["cny"] if b["converted"] else None,
            "count": b["count"],
        }
        for b in sorted(buckets.values(), key=lambda x: -x["native"])
    ]

    converted = bool(rates) and all(b["converted"] for b in buckets.values())
    market_value_cny: float | None = None
    total_value: float | None = None
    cash_pct: float | None = None
    if converted:
        market_value_cny = round(sum(float(b["cny"] or 0) for b in buckets.values()), 2)
        total_value = round(market_value_cny + (cash or 0), 2)
        if cash is not None:
            cash_pct = 0.0 if total_value <= 0 else round(cash / total_value * 100, 2)

    # ── 权重：能折算就用人民币口径，否则不给（避免跨币种胡算） ──
    # 分母是**持仓市值（不含现金）**——与 risk_policy_service.portfolio_nav()
    # 和前端 computeWeights 一致，否则「单票上限 15%」会和页面上的权重打架。
    weights: dict[str, float] | None = None
    max_weight = 0.0
    if converted and market_value_cny and market_value_cny > 0:
        weights = {}
        for item in items:
            ccy = holding_currency(item)
            cny = to_cny_amount(float(item.market_value or 0), ccy, rates) or 0.0
            pct = round(cny / market_value_cny * 100, 2)
            weights[item.symbol] = pct
            max_weight = max(max_weight, pct)

    return {
        # 折合口径（无汇率时为 None）
        "market_value": market_value_cny,
        "total_value": total_value,
        "weights": weights,
        "max_weight_pct": round(max_weight, 2),
        "cash_pct": cash_pct,
        # 分币种小计（零依赖，永远可用）
        "by_currency": by_currency,
        "currencies": [b["currency"] for b in by_currency],
        "converted": converted,
        # 其它
        "positions": len(items),
        "available_cash": cash,
        "fx": fx,
        "source": "local_sqlite",
    }

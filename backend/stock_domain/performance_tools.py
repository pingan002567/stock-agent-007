"""盘后表现：今日收益 / 逐只贡献 / 现金变动 / 基准对比 / 回撤 / 待办分诊。

为什么不用 `quote.change_pct`：盘后它常常是 0（provider 只给昨收），
直接拿它算收益会写出"今日 0.00%"这种假结论。这里统一用**日K的最后两根收盘价**。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.schemas import HoldingPosition
from backend.stock_domain import fx as fx_service
from backend.stock_domain.portfolio_tools import (
    cash_buckets_with_cny,
    holding_currency,
    read_cash_buckets,
)
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.trading_calendar import expected_bar_date

#: 组合对比的基准（sina 指数代码）
BENCHMARKS = (("sh000300", "沪深300"), ("sh000905", "中证500"))


def _bar_key(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "").strip()


def _last_two_closes(symbol: str) -> tuple[float, float, str] | None:
    try:
        hist = provider_router.get_history(symbol, days=3)
    except Exception:
        return None
    items = (hist or {}).get("items") or []
    if len(items) < 2:
        return None
    rows = sorted(items, key=lambda r: _bar_key(r.get("date")))
    try:
        return float(rows[-1]["close"]), float(rows[-2]["close"]), _bar_key(rows[-1].get("date"))
    except (KeyError, TypeError, ValueError):
        return None


def _today_key() -> str:
    return datetime.now().strftime("%Y%m%d")


def build_triage(services: Any) -> dict[str, Any]:
    """待办分诊：把"必须处理"和"可暂时忽略"分开，而不是把 17 条全列出来。

    判据（故意保守，宁可少报"必须处理"）：
    - 必须：inbox 里 priority=high 且仍 open，或监控事件 severity=high
    - 其余：可忽略（计入计数，不逐条展开）
    """
    must: list[dict[str, Any]] = []
    counts = {"inbox_open": 0, "inbox_high": 0, "monitor_events": 0, "monitor_high": 0}

    try:
        items = services.review_inbox_service.list_items(limit=200)
    except Exception:
        items = []
    for item in items:
        status = str(getattr(item, "status", "") or "")
        if status not in ("open", "Open", "OPEN"):
            continue
        counts["inbox_open"] += 1
        priority = str(getattr(item, "priority", "") or "").lower()
        if priority == "high":
            counts["inbox_high"] += 1
            must.append({
                "kind": "inbox",
                "id": getattr(item, "item_key", ""),
                "title": getattr(item, "title", ""),
                "reason": f"高优先待办 · {getattr(item, 'item_type', '')}",
            })

    try:
        events = services.monitor_service.list_events(limit=100)
    except Exception:
        events = []
    for ev in events or []:
        counts["monitor_events"] += 1
        severity = str(getattr(ev, "severity", "") or "").lower()
        if severity == "high":
            counts["monitor_high"] += 1
            must.append({
                "kind": "monitor",
                "id": getattr(ev, "event_id", ""),
                "title": getattr(ev, "title", "") or getattr(ev, "message", ""),
                "reason": f"高严重度监控事件 · {getattr(ev, 'symbol', '')}",
            })

    # 去重 + 截断：报告里最多点名 5 条，其余只给数字
    seen: set[str] = set()
    deduped = []
    for row in must:
        key = f"{row['kind']}:{row['id']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return {
        "must_handle": deduped[:5],
        "must_count": len(deduped),
        "can_ignore_count": max(
            0, (counts["inbox_open"] - counts["inbox_high"]) + (counts["monitor_events"] - counts["monitor_high"])
        ),
        "counts": counts,
        "hint": "报告里只写 must_handle 的前 3 条 + 汇总数字，不要把全部待办罗列出来",
    }


def build_daily_performance(services: Any) -> dict[str, Any]:
    """一次性算出盘后报告需要的事实，避免模型自己拼公式算错。"""
    repo = services.repo
    holdings: list[HoldingPosition] = list(repo.list_holdings())
    payload = fx_service.get_rates()
    rates = fx_service.rates_for_conversion(payload)
    buckets = read_cash_buckets(repo)
    cash_rows, cash_cny = cash_buckets_with_cny(buckets, rates)

    # 15:15 跑盘后报告时，今日日K常常还没落地。这时**不能**把"昨天 vs 前天"当成今日收益，
    # 必须标成未更新（宁缺毋假）。
    expected = expected_bar_date("CN").strftime("%Y%m%d")

    # ── 逐只：今收/昨收日K口径 ──
    contributors: list[dict[str, Any]] = []
    market_value_cny = 0.0
    prev_value_cny = 0.0
    day_pnl_cny = 0.0
    degraded: list[str] = []
    for item in holdings:
        ccy = holding_currency(item)
        rate = (rates or {}).get(ccy, 1.0 if ccy == "CNY" else None)
        pair = _last_two_closes(item.symbol)
        if pair is not None and pair[2] != expected:
            pair = None  # 最新一根不是"应有交易日" → 今日收益未知
        if pair is None or rate is None:
            degraded.append(item.symbol)
            # 拿不到日K就退化成"当前市值"，不参与当日盈亏
            market_value_cny += float(item.market_value or 0) * (rate or 1.0)
            continue
        close, prev, bar_date = pair
        qty = float(item.quantity or 0)
        native_pnl = (close - prev) * qty
        pnl = native_pnl * rate
        market_value_cny += close * qty * rate
        prev_value_cny += prev * qty * rate
        day_pnl_cny += pnl
        contributors.append({
            "symbol": item.symbol,
            "name": item.name,
            "quantity": qty,
            "currency": ccy,
            "prev_close": round(prev, 4),
            "close": round(close, 4),
            "change_pct": round((close / prev - 1) * 100, 2) if prev else None,
            "day_pnl": round(pnl, 2),
            "weight_pct": round((close * qty * rate) / market_value_cny * 100, 2) if market_value_cny else None,
            "bar_date": bar_date,
            "cost": item.cost,
        })

    cash_total = cash_cny if cash_cny is not None else 0.0
    nav = round(market_value_cny + cash_total, 2)
    # 一只能对上日K都没有 → 今日收益整体不可用（不能拿 0 或昨天的数据充数）
    day_available = bool(contributors)
    prev_nav = round(prev_value_cny + cash_total, 2) if day_available else None
    day_pnl = round(day_pnl_cny, 2) if day_available else None
    day_return_pct = (
        round(day_pnl_cny / prev_nav * 100, 2) if (day_available and prev_nav and prev_nav > 0) else None
    )

    contributors.sort(key=lambda r: r["day_pnl"])
    negatives = [c for c in contributors if c["day_pnl"] < 0][:3]
    positives = [c for c in reversed(contributors) if c["day_pnl"] > 0][:3]

    # ── 净值快照 & 回撤 ──
    today = date.today().isoformat()
    try:
        repo.upsert_nav_snapshot(today, nav, round(market_value_cny, 2), round(cash_total, 2))
        peak = repo.peak_nav()
    except Exception:
        peak = None
    drawdown_pct = round((nav / peak - 1) * 100, 2) if peak and peak > 0 else None

    # ── 今日现金变动（来自流水，只算 buy/sell）──
    flows = {"buy_count": 0, "sell_count": 0, "net_cash": 0.0, "adjust_count": 0}
    try:
        for row in repo.list_cash_ledger(limit=200):
            if not str(row.get("created_at") or "").startswith(today):
                continue
            reason = str(row.get("reason") or "")
            if reason == "buy":
                flows["buy_count"] += 1
                flows["net_cash"] += float(row.get("delta") or 0)
            elif reason == "sell":
                flows["sell_count"] += 1
                flows["net_cash"] += float(row.get("delta") or 0)
            elif reason == "adjust":
                flows["adjust_count"] += 1
    except Exception:
        pass

    # ── 基准对比（市场复盘里的指数快照，5min 缓存）──
    benchmarks: list[dict[str, Any]] = []
    try:
        review = provider_router.get_market_review()
        by_code = {str(i.get("code") or "").lower(): i for i in (review.get("indices") or [])}
        for code, label in BENCHMARKS:
            row = by_code.get(code)
            if not row or row.get("change_pct") is None:
                continue
            chg = float(row["change_pct"])
            benchmarks.append({
                "code": code,
                "name": label,
                "change_pct": round(chg, 2),
                "excess_pct": round((day_return_pct or 0) - chg, 2),
            })
    except Exception:
        pass

    # ── 距成本（止盈止损距离的替代口径：没有结构化止盈损字段）──
    distance = [
        {
            "symbol": c["symbol"], "name": c["name"],
            "pnl_pct": round((c["close"] / float(c["cost"]) - 1) * 100, 2) if c.get("cost") else None,
            "close": c["close"], "cost": c["cost"],
        }
        for c in contributors if c.get("cost")
    ]
    distance.sort(key=lambda r: abs(r["pnl_pct"] or 0))

    return {
        "as_of": today,
        "portfolio": {
            "nav": nav,
            "prev_nav": prev_nav,
            "market_value": round(market_value_cny, 2),
            "cash": round(cash_total, 2),
            "cash_pct": round(cash_total / nav * 100, 2) if nav > 0 else None,
            "day_pnl": day_pnl,
            "day_return_pct": day_return_pct,
            "day_pnl_available": day_available,
            "expected_bar": expected,
            "drawdown_pct": drawdown_pct,
            "peak_nav": peak,
        },
        "contributors": {"negative": negatives, "positive": positives, "all": contributors},
        "cash_flows": flows,
        "benchmarks": benchmarks,
        "distance_to_cost": distance,
        "triage": build_triage(services),
        "cash_by_currency": cash_rows,
        "degraded_symbols": degraded,
        "data_health": {
            "price_basis": "daily_kline_close" if day_available and not degraded else (
                "mixed(部分标的缺当日日K)" if day_available else "today_bar_missing(今日日K未更新)"
            ),
            "fx_degraded": cash_cny is None or not rates,
            "benchmark_available": bool(benchmarks),
        },
    }

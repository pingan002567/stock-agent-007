from __future__ import annotations

from statistics import pstdev
from typing import Any, Iterable

from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.result_projection import (
    DETAIL_FULL,
    DETAIL_SUMMARY,
    project_items,
    truncation_note,
)
from backend.stock_domain.series_order import sort_history_items

# summary 档默认带回的近端样本条数与字段。够模型看清最近走势，又不至于把整段
# K 线塞进线程历史。
SUMMARY_SAMPLE_LIMIT = 5
SUMMARY_FIELDS = ("date", "open", "high", "low", "close", "volume")
OHLC_FIELDS = ("date", "open", "high", "low", "close", "volume")

_MORE_HINT = "需要完整 K 线时用 detail='full'；只要部分字段用 detail='ohlc' + fields/limit。"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return None if num != num else num


def summarize_history(items: list[dict[str, Any]]) -> dict[str, Any]:
    """把 N 根 K 线压成一组统计量（items 为 newest-first）。"""
    closes = [c for c in (_num(item.get("close")) for item in items) if c is not None]
    highs = [h for h in (_num(item.get("high")) for item in items) if h is not None]
    lows = [low for low in (_num(item.get("low")) for item in items) if low is not None]
    volumes = [v for v in (_num(item.get("volume")) for item in items) if v is not None]
    dates = [str(item.get("date") or "") for item in items if str(item.get("date") or "")]

    summary: dict[str, Any] = {"bars": len(items)}
    if dates:
        summary["period"] = {"start": dates[-1], "end": dates[0]}
    if closes:
        latest, oldest = closes[0], closes[-1]
        summary["close"] = {"latest": round(latest, 4), "first": round(oldest, 4)}
        if oldest:
            summary["change_pct"] = round((latest - oldest) / oldest * 100, 2)
    if highs:
        summary["high"] = round(max(highs), 4)
    if lows:
        summary["low"] = round(min(lows), 4)
    if volumes:
        summary["avg_volume"] = round(sum(volumes) / len(volumes), 2)

    # 日收益率标准差：newest-first，所以 i 相对 i+1 是「后一天比前一天」
    returns = [
        (closes[i] - closes[i + 1]) / closes[i + 1]
        for i in range(len(closes) - 1)
        if closes[i + 1]
    ]
    if len(returns) > 1:
        summary["daily_volatility_pct"] = round(pstdev(returns) * 100, 3)
    if closes:
        peak = closes[-1]
        drawdown = 0.0
        for price in reversed(closes):
            peak = max(peak, price)
            if peak:
                drawdown = min(drawdown, (price - peak) / peak)
        summary["max_drawdown_pct"] = round(drawdown * 100, 2)
    return summary


def get_daily_history(
    symbol: str,
    days: int = 30,
    detail: str = DETAIL_SUMMARY,
    fields: Iterable[str] | None = None,
    limit: int | None = None,
) -> dict:
    """历史 K 线。

    ``detail`` 决定返回体量：``summary``（默认）只回统计量 + 最近几根；
    ``ohlc`` 按 ``fields``/``limit`` 投影；``full`` 返回原始全量。
    """
    raw = provider_router.get_history(symbol, days)
    items = raw.get("items")
    if not isinstance(items, list):
        return raw

    items = sort_history_items(items)
    # provider_router 命中缓存时返回的是共享 dict：投影结果必须写进副本，
    # 否则下一次调用拿到的是被上一次截断过的数据。
    payload = {key: value for key, value in raw.items() if key != "items"}
    payload["detail"] = detail
    if detail == DETAIL_FULL:
        payload["items"] = items
        return payload

    total = len(items)
    if detail == DETAIL_SUMMARY:
        payload["summary"] = summarize_history(items)
        sample_limit = limit if limit and limit > 0 else SUMMARY_SAMPLE_LIMIT
        payload["items"] = project_items(items, fields or SUMMARY_FIELDS, sample_limit)
    else:
        payload["items"] = project_items(items, fields or OHLC_FIELDS, limit)

    note = truncation_note(
        returned=len(payload["items"]),
        total=total,
        tool="get_daily_history",
        hint=_MORE_HINT,
    )
    if note:
        payload["truncated"] = note
    return payload

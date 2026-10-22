"""A 股短线情绪**数据**（不评分、不分类，交给模型自己判断）。

只给事实：涨停家数、连板梯队、炸板率、昨日涨停今日红盘率、跌停家数、涨跌家数、
涨停板块集中度。**不产出"温度分 / 阶段 / 该不该做"这类结论** —— 那些是模型的活。

数据来源（全部 akshare / 东财，无需 token）：
- 涨停池 `stock_zt_pool_em`：代码/名称/连板数/炸板次数/封板资金/所属行业
- 炸板池 `stock_zt_pool_zbgc_em`
- 昨日涨停池 `stock_zt_pool_previous_em`（当日涨跌幅）
- 跌停池 `stock_zt_pool_dtgc_em`
- 涨跌家数/成交额：复用 provider_router.get_market_review() 的 breadth（已缓存）

纪律（与仓库其它工具一致）：
- 任一块拉不到就进 `coverage.missing` 并置 `degraded`，**不猜、不编数字**
- 非交易日回退到最近一个已收盘交易日，并在 `as_of` 里写清楚
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any


def _as_int(value: Any) -> int:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _trade_date() -> date:
    """最近一个已收盘的交易日（周末/盘前回退）。"""
    from backend.stock_domain.trading_calendar import expected_bar_date

    return expected_bar_date("CN")


def _pool(fn_name: str, day: str) -> tuple[list[dict[str, Any]], str | None]:
    """拉一个涨停/炸板/跌停池，失败返回 (空, 原因)。"""
    try:
        import io
        import os
        from contextlib import redirect_stderr, redirect_stdout

        import akshare as ak  # type: ignore[import-not-found]

        fn = getattr(ak, fn_name, None)
        if fn is None:
            return [], f"akshare 无 {fn_name}"
        # akshare 的涨停池会打 tqdm 进度条（stdout/stderr 都有），别污染服务端日志
        os.environ.setdefault("TQDM_DISABLE", "1")
        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            df = fn(date=day)
        if df is None or len(df) == 0:
            return [], None
        return df.to_dict("records"), None
    except Exception as exc:  # noqa: BLE001 - 第三方接口什么都可能抛
        return [], f"{fn_name}: {type(exc).__name__}"


def _breadth() -> tuple[dict[str, Any], str | None]:
    """涨跌家数/成交额：复用已有 market review，避免再拉一次全市场快照。"""
    try:
        import io
        import os
        from contextlib import redirect_stderr, redirect_stdout

        from backend.stock_domain.provider_router import provider_router

        # market review 内部走 akshare 全市场快照，同样会刷 tqdm 进度条
        os.environ.setdefault("TQDM_DISABLE", "1")
        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            review = provider_router.get_market_review() or {}
        breadth = review.get("breadth") or {}
        return {
            "rising": _as_int(breadth.get("rising_count")),
            "falling": _as_int(breadth.get("falling_count")),
            "flat": _as_int(breadth.get("flat_count")),
            "sample_size": _as_int(breadth.get("sample_size")),
            "turnover": _as_float((review.get("turnover") or {}).get("a_share_total")),
            "source": review.get("source"),
        }, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"market_review: {type(exc).__name__}"


def get_market_sentiment() -> dict:
    """A 股短线情绪原始数据：涨停/连板/炸板/赚钱效应/涨跌家数/涨停板块。

    只做**聚合**（计数、排序、比值），不做**判断**（温度分、阶段、该不该做）。
    模型拿到这些数字后自己分析。
    """
    day = _trade_date()
    day_str = day.strftime("%Y%m%d")
    missing: list[str] = []
    notes: list[str] = []

    zt_rows, err = _pool("stock_zt_pool_em", day_str)
    if err:
        missing.append("limit_up_pool")
        notes.append(err)
    broken_rows, err = _pool("stock_zt_pool_zbgc_em", day_str)
    if err:
        missing.append("broken_pool")
        notes.append(err)
    prev_rows, err = _pool("stock_zt_pool_previous_em", day_str)
    if err:
        missing.append("previous_limit_up")
        notes.append(err)
    dt_rows, err = _pool("stock_zt_pool_dtgc_em", day_str)
    if err:
        missing.append("limit_down_pool")
        notes.append(err)
    breadth, err = _breadth()
    if err:
        missing.append("breadth")
        notes.append(err)

    # ── 连板梯队（纯计数）───────────────────────────────────────
    ladder: dict[str, int] = {}
    max_streak = 0
    for row in zt_rows:
        streak = max(1, _as_int(row.get("连板数")))
        max_streak = max(max_streak, streak)
        key = f"{streak}板"
        ladder[key] = ladder.get(key, 0) + 1
    limit_up_count = len(zt_rows)

    # ── 涨停板块集中度（纯计数：同一行业 ≥3 家）──────────────────
    sector_hits: dict[str, int] = {}
    for row in zt_rows:
        sector = str(row.get("所属行业") or "").strip()
        if sector:
            sector_hits[sector] = sector_hits.get(sector, 0) + 1
    hot_sectors = [
        {"sector": k, "count": v}
        for k, v in sorted(sector_hits.items(), key=lambda kv: -kv[1])
        if v >= 3
    ][:8]

    # ── 炸板率（纯比值）─────────────────────────────────────────
    broken_count = len(broken_rows)
    attempts = limit_up_count + broken_count
    broken_rate = round(broken_count / attempts, 4) if attempts else None

    # ── 昨日涨停今日红盘率（纯比值）─────────────────────────────
    red = sum(1 for row in prev_rows if _as_float(row.get("涨跌幅")) > 0)
    red_ratio = round(red / len(prev_rows), 4) if prev_rows else None

    degraded = bool(missing)
    return {
        "as_of": day.isoformat(),
        "source": "akshare/eastmoney + market_review",
        "degraded": degraded,
        "degraded_reason": "；".join(notes) if notes else None,
        "coverage": {
            "missing": missing,
            "blocks": ["limit_up", "broken", "previous_limit_up", "limit_down", "breadth"],
        },
        "limit_up": {
            "count": limit_up_count,
            "max_streak": max_streak,
            "ladder": dict(sorted(ladder.items(), key=lambda kv: -int(kv[0].replace("板", "")))),
            "sealed_amount_top": [
                {
                    "symbol": str(row.get("代码") or ""),
                    "name": str(row.get("名称") or ""),
                    "streak": _as_int(row.get("连板数")),
                    "sealed": _as_float(row.get("封板资金")),
                    "sector": str(row.get("所属行业") or ""),
                }
                for row in sorted(zt_rows, key=lambda r: -_as_float(r.get("封板资金")))[:5]
            ],
            "hot_sectors": hot_sectors,
        },
        "limit_down": {"count": len(dt_rows)},
        "broken": {"count": broken_count, "rate": broken_rate},
        "breadth": breadth,
        "previous_limit_up": {
            "count": len(prev_rows),
            "red_count": red,
            "red_ratio": red_ratio,
        },
    }

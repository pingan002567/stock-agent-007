"""A 股市场情绪温度计。

为什么需要它：`get_market_structure` 给的是**个股**的量价与筹码，`get_market_review`
给的是指数和涨跌家数；但 A 股的短线情绪是**全市场**的现象 —— 涨停家数、连板高度、
炸板率、昨日涨停今日红盘率，这四个才是判断"现在能不能做"的温度计。

数据来源（全部 akshare / 东财，无需 token）：
- 涨停池 `stock_zt_pool_em`：代码/名称/连板数/炸板次数/封板资金/所属行业
- 炸板池 `stock_zt_pool_zbgc_em`
- 昨日涨停池 `stock_zt_pool_previous_em`（当日涨跌幅 → 赚钱效应）
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

# 情绪分权重（合计 100）—— 改这里要同步改 doc/DESKTOP_PET_DESIGN 无关，
# 但必须同步 skills/custom/market-sentiment/SKILL.md 里的口径说明。
W_LIMIT_UP = 25.0      # 涨停家数：50 家满分
W_STREAK = 20.0        # 连板高度：6 板满分
W_BREADTH = 25.0       # 涨跌家数比
W_BROKEN = 15.0        # 炸板率（反向）
W_RED = 15.0           # 昨日涨停今日红盘率

LIMIT_UP_FULL = 50.0
STREAK_FULL = 6.0
BROKEN_GOOD = 0.20     # 炸板率 20% 视为健康
BROKEN_BAD = 0.60      # 60% 视为极差


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


def _phase_of(temperature: float) -> tuple[str, str]:
    """温度 → 情绪阶段。阈值刻意粗，避免把噪音当信号。"""
    if temperature >= 80:
        return "高潮", "涨停密集、连板不断，拥挤度最高，追高赔率最差"
    if temperature >= 60:
        return "升温", "赚钱效应扩散，可以参与但要看分歧后能否走强"
    if temperature >= 40:
        return "修复", "多空分化，只有主线能走，杂毛容易被埋"
    if temperature >= 20:
        return "退潮", "接力资金撤退，次日溢价转负，优先防守"
    return "冰点", "涨停稀少、炸板率高，等待修复信号而不是抄底"


def _record_and_history(snapshot: dict) -> tuple[int, list[dict[str, Any]]]:
    """把当天快照落库（幂等），并返回「当前阶段连续天数」与近 30 天曲线。

    依赖 provider_router.repo（bootstrap 里已注入）。repo 不可用时静默跳过 ——
    情绪温度计仍可用，只是没有周期位置。
    """
    try:
        from backend.schemas import now_iso

        from backend.stock_domain.provider_router import provider_router
    except Exception:  # noqa: BLE001
        return 0, []
    repo = getattr(provider_router, "repo", None)
    if repo is None:
        return 0, []
    snapshot["recorded_at"] = now_iso()
    try:
        repo.record_market_sentiment(snapshot)
        streak = repo.phase_streak(snapshot.get("phase"))
        history = repo.list_market_sentiment(limit=30)
    except Exception:  # noqa: BLE001
        return 0, []
    return streak, history


def get_market_sentiment() -> dict:
    """A 股全市场情绪温度计（涨停/连板/炸板/赚钱效应 + 温度分与阶段）。"""
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

    # ── 连板梯队 ────────────────────────────────────────────────
    ladder: dict[str, int] = {}
    max_streak = 0
    for row in zt_rows:
        streak = max(1, _as_int(row.get("连板数")))
        max_streak = max(max_streak, streak)
        key = f"{streak}板"
        ladder[key] = ladder.get(key, 0) + 1
    limit_up_count = len(zt_rows)

    # 涨停板块集中度：游资在炒什么（同一行业 ≥3 家才算抱团）
    sector_hits: dict[str, int] = {}
    for row in zt_rows:
        sector = str(row.get("所属行业") or "").strip()
        if sector:
            sector_hits[sector] = sector_hits.get(sector, 0) + 1
    hot_sectors = [
        {"sector": k, "count": v}
        for k, v in sorted(sector_hits.items(), key=lambda kv: -kv[1])
        if v >= 3
    ][:5]

    # ── 炸板率 ──────────────────────────────────────────────────
    broken_count = len(broken_rows)
    attempts = limit_up_count + broken_count
    broken_rate = round(broken_count / attempts, 4) if attempts else None

    # ── 昨日涨停今日红盘率（赚钱效应）────────────────────────────
    red = sum(1 for row in prev_rows if _as_float(row.get("涨跌幅")) > 0)
    red_ratio = round(red / len(prev_rows), 4) if prev_rows else None

    # ── 温度分 ──────────────────────────────────────────────────
    parts: dict[str, float] = {}
    parts["limit_up"] = min(W_LIMIT_UP, limit_up_count / LIMIT_UP_FULL * W_LIMIT_UP) if zt_rows else 0.0
    parts["streak"] = min(W_STREAK, max_streak / STREAK_FULL * W_STREAK) if zt_rows else 0.0
    rising, falling = breadth.get("rising", 0), breadth.get("falling", 0)
    if breadth:
        ratio = rising / max(1, rising + falling)
        parts["breadth"] = max(0.0, min(W_BREADTH, (ratio - 0.2) / 0.6 * W_BREADTH))
    else:
        parts["breadth"] = 0.0
    if broken_rate is not None:
        span = BROKEN_BAD - BROKEN_GOOD
        parts["broken"] = max(0.0, min(W_BROKEN, (BROKEN_BAD - broken_rate) / span * W_BROKEN))
    else:
        parts["broken"] = 0.0
    if red_ratio is not None:
        parts["red"] = max(0.0, min(W_RED, (red_ratio - 0.2) / 0.6 * W_RED))
    else:
        parts["red"] = 0.0

    covered = [k for k in ("limit_up", "streak", "breadth", "broken", "red") if parts[k] > 0]
    # 全部缺失就不要给分（0 分会误导成"冰点"）
    temperature = round(sum(parts.values()), 1) if covered else None
    phase, phase_hint = _phase_of(temperature) if temperature is not None else ("未知", "")

    # 背离守卫：A 股常见"涨停不少、但全市场普跌"的结构性行情。
    # 只看涨停/赚钱效应会把这种日子判成"升温"，误导成可以普涨参与 ——
    # 全市场下跌家数占绝对多数时，温度封顶 55 并明确标注分化。
    divergence = None
    if temperature is not None and breadth and (rising + falling) > 0:
        up_ratio = rising / (rising + falling)
        if up_ratio < 0.30 and limit_up_count >= 30:
            divergence = (
                f"涨停 {limit_up_count} 家但全市场仅 {up_ratio:.0%} 上涨"
                f"（涨 {rising} / 跌 {falling}）—— 结构性分化，不是普涨"
            )
            temperature = min(temperature, 55.0)
            phase, phase_hint = "分化", "只有主线能走；按板块做，不要当普涨行情追"

    degraded = bool(missing)
    result = {
        "as_of": day.isoformat(),
        "source": "akshare/eastmoney + market_review",
        "degraded": degraded,
        "degraded_reason": "；".join(notes) if notes else None,
        "coverage": {
            "missing": missing,
            "blocks": ["limit_up", "broken", "previous_limit_up", "limit_down", "breadth"],
        },
        "temperature": temperature,
        "phase": phase,
        "phase_hint": phase_hint,
        "divergence": divergence,
        "score_parts": {k: round(v, 1) for k, v in parts.items()},
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
        "formula": {
            "limit_up": f"min({W_LIMIT_UP:.0f}, 涨停数/{LIMIT_UP_FULL:.0f}*{W_LIMIT_UP:.0f})",
            "streak": f"min({W_STREAK:.0f}, 最高板/{STREAK_FULL:.0f}*{W_STREAK:.0f})",
            "breadth": f"涨跌比 0.2→0 / 0.8→{W_BREADTH:.0f}",
            "broken": f"炸板率 {BROKEN_GOOD:.0%}→{W_BROKEN:.0f} / {BROKEN_BAD:.0%}→0",
            "red": f"昨日涨停红盘率 0.2→0 / 0.8→{W_RED:.0f}",
        },
    }
    # 落库 + 周期位置（repo 不可用时静默跳过，温度计仍可用）
    phase_day, history = _record_and_history(result)
    result["phase_day"] = phase_day
    result["history"] = history
    return result

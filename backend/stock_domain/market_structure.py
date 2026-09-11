"""个股市场结构：技术量价 + 快照估值/流动性 + A 股筹码 / 资金流。

硬约束：禁止 mock；港美股不得输出获利/套牢比例；缺数据用 degraded + missing。
"""
from __future__ import annotations

from typing import Any

from backend.schemas import now_iso
from backend.stock_domain.catalog import get_stock, normalize_symbol
from backend.stock_domain.history_tools import get_daily_history
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.providers import AkShareMarketDataProvider, _safe_float
from backend.stock_domain.series_order import _parse_time


def _bars_ascending(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _parse_time(item.get("date")))


def _num(bar: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _safe_float(bar.get(key))
        if parsed is not None:
            return parsed
    return None


def _volume(bar: dict[str, Any]) -> tuple[float | None, bool]:
    vol = _num(bar, "volume")
    close = _num(bar, "close")
    amount = _num(bar, "amount")
    if vol is not None and vol > 0:
        return vol, False
    if amount is not None and amount > 0 and close is not None and close > 0:
        return round(amount / close, 0), True
    return vol if vol is not None else 0.0, False


def _sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return round(sum(values[-n:]) / n, 4)


def _ema_series(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (n + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * k + out[-1] * (1.0 - k))
    return out


def _rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = _num(bars[i], "high") or _num(bars[i], "close") or 0.0
        low = _num(bars[i], "low") or _num(bars[i], "close") or 0.0
        prev_close = _num(bars[i - 1], "close") or 0.0
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for value in trs[period:]:
        atr = (atr * (period - 1) + value) / period
    return round(atr, 4)


def compute_technical(items: list[dict[str, Any]]) -> dict[str, Any]:
    """从日 K 计算技术量价。输入可 newest-first；内部转升序。"""
    missing: list[str] = []
    bars = _bars_ascending([item for item in items if _num(item, "close") is not None])
    if not bars:
        return {
            "degraded": True,
            "reason": "无可用 K 线",
            "missing": ["history"],
            "bar_count": 0,
        }

    closes = [_num(b, "close") or 0.0 for b in bars]
    highs = [_num(b, "high") or c for b, c in zip(bars, closes)]
    lows = [_num(b, "low") or c for b, c in zip(bars, closes)]
    volumes: list[float] = []
    derived = 0
    for bar in bars:
        vol, is_derived = _volume(bar)
        volumes.append(vol or 0.0)
        if is_derived:
            derived += 1

    ma = {n: _sma(closes, n) for n in (5, 10, 20, 60)}
    for n, value in ma.items():
        if value is None:
            missing.append(f"ma{n}")

    rsi = _rsi_wilder(closes)
    if rsi is None:
        missing.append("rsi14")
    atr = _atr(bars)
    if atr is None:
        missing.append("atr14")

    macd_line = signal_line = hist = None
    if len(closes) >= 35:
        ema12 = _ema_series(closes, 12)
        ema26 = _ema_series(closes, 26)
        macd_series = [a - b for a, b in zip(ema12, ema26)]
        signal_series = _ema_series(macd_series, 9)
        macd_line = round(macd_series[-1], 4)
        signal_line = round(signal_series[-1], 4)
        hist = round(macd_line - signal_line, 4)
    else:
        missing.append("macd")

    volume_ratio = None
    if len(volumes) >= 21 and sum(volumes[-21:-1]) > 0:
        volume_ratio = round(volumes[-1] / (sum(volumes[-21:-1]) / 20), 3)
    else:
        missing.append("volume_ratio")

    support_20 = round(min(lows[-20:]), 4) if len(lows) >= 20 else None
    resistance_20 = round(max(highs[-20:]), 4) if len(highs) >= 20 else None
    support_60 = round(min(lows[-60:]), 4) if len(lows) >= 60 else None
    resistance_60 = round(max(highs[-60:]), 4) if len(highs) >= 60 else None
    if support_20 is None:
        missing.append("support_20")
    if resistance_20 is None:
        missing.append("resistance_20")

    first = closes[0]
    last = closes[-1]
    range_pct = round((last - first) / first * 100, 2) if first else None

    ma_stack = None
    if ma[5] is not None and ma[10] is not None and ma[20] is not None:
        if ma[5] > ma[10] > ma[20]:
            ma_stack = "bullish"
        elif ma[5] < ma[10] < ma[20]:
            ma_stack = "bearish"
        else:
            ma_stack = "mixed"

    volume_note = "成交量由额反推" if derived else None
    if derived and all(v <= 0 for v in volumes):
        volume_note = "成交量为 0"
        if "volume_ratio" not in missing:
            missing.append("volume_ratio")
            volume_ratio = None

    return {
        "degraded": False,
        "reason": None,
        "bar_count": len(bars),
        "as_of": str(bars[-1].get("date") or "")[:10],
        "last": last,
        "range_pct": range_pct,
        "ma5": ma[5],
        "ma10": ma[10],
        "ma20": ma[20],
        "ma60": ma[60],
        "ma_stack": ma_stack,
        "rsi14": rsi,
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": hist,
        "atr14": atr,
        "volume_ratio": volume_ratio,
        "support_20": support_20,
        "resistance_20": resistance_20,
        "support_60": support_60,
        "resistance_60": resistance_60,
        "volume_note": volume_note,
        "missing": missing,
    }


def _vwap(bars: list[dict[str, Any]], window: int = 20) -> float | None:
    sample = bars[-window:]
    num = 0.0
    den = 0.0
    for bar in sample:
        close = _num(bar, "close")
        vol, _ = _volume(bar)
        if close is None or not vol:
            continue
        num += close * vol
        den += vol
    if den <= 0:
        return None
    return round(num / den, 4)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _ratio_unit(value: float | None) -> float | None:
    """获利比例可能是 0-1 或 0-100。"""
    if value is None:
        return None
    if value > 1.5:
        return round(value / 100.0, 4)
    return round(value, 4)


def _is_st_or_halted(stock: dict[str, Any]) -> bool:
    name = str(stock.get("name") or "")
    upper = name.upper()
    return "ST" in upper or "停牌" in name


def _volume_dead(bars: list[dict[str, Any]]) -> bool:
    sample = bars[-10:] if len(bars) >= 10 else bars
    if not sample:
        return True
    return all((_volume(bar)[0] or 0.0) <= 0 for bar in sample)


def _chip_quality(bars: list[dict[str, Any]], bar_count: int) -> tuple[str, str | None]:
    if bar_count < 60:
        return "low", "上市不足 60 个交易日，筹码样本短"
    if _volume_dead(bars):
        return "low", "近端几乎无量，CYQ 可能失真"
    if len(bars) >= 4:
        closes = [_num(bar, "close") or 0.0 for bar in bars[-4:]]
        spikes = 0
        for prev, cur in zip(closes, closes[1:]):
            if prev and abs(cur - prev) / prev >= 0.095:
                spikes += 1
        if spikes >= 2:
            return "low", "近端连续大幅波动/涨跌停，CYQ 可能失真"
    return "normal", None


def _chip_from_row(row: dict[str, Any], last: float | None, bars: list[dict[str, Any]]) -> dict[str, Any]:
    profit = _ratio_unit(_safe_float(row.get("获利比例") or row.get("获利盘比例")))
    avg_cost = _safe_float(row.get("平均成本") or row.get("market_avg_cost"))
    low90 = _safe_float(row.get("90成本-低") or row.get("90成本低"))
    high90 = _safe_float(row.get("90成本-高") or row.get("90成本高"))
    conc90 = _safe_float(row.get("90集中度"))
    low70 = _safe_float(row.get("70成本-低") or row.get("70成本低"))
    high70 = _safe_float(row.get("70成本-高") or row.get("70成本高"))
    conc70 = _safe_float(row.get("70集中度"))
    as_of = str(row.get("日期") or row.get("date") or "")[:10]
    trapped = round(1.0 - profit, 4) if profit is not None else None
    vs_avg = None
    if last and avg_cost:
        vs_avg = round((last - avg_cost) / avg_cost * 100, 2)
    if conc90 is None and last and low90 is not None and high90 is not None and last > 0:
        conc90 = round((high90 - low90) / last, 4)
    quality, quality_reason = _chip_quality(bars, len(bars))
    notes = ["非实时逐笔还原", "解禁/增发后分布会突变"]
    if quality_reason:
        notes.append(quality_reason)
    if profit is None and avg_cost is None:
        return {
            "degraded": True,
            "reason": "筹码行缺少获利比例与平均成本",
        }
    return {
        "degraded": False,
        "reason": None,
        "method": "eastmoney_cyq",
        "as_of": as_of,
        "quality": quality,
        "profit_ratio": profit,
        "trapped_ratio": trapped,
        "market_avg_cost": avg_cost,
        "price_vs_avg_cost_pct": vs_avg,
        "cost_90_low": low90,
        "cost_90_high": high90,
        "concentration_90": conc90,
        "cost_70_low": low70,
        "cost_70_high": high70,
        "concentration_70": conc70,
        "notes": notes,
    }


def _short_reason(prefix: str, exc: Exception) -> str:
    text = str(exc)
    if "RemoteDisconnected" in text or "Connection aborted" in text or "ConnectionError" in type(exc).__name__:
        return f"{prefix}：上游连接中断，未编造数据"
    return f"{prefix}：{text[:160]}"


def _akshare_primary() -> AkShareMarketDataProvider | None:
    primary = provider_router.primary
    return primary if isinstance(primary, AkShareMarketDataProvider) else None


def _chip_block(market: str, symbol: str, last: float | None, bars: list[dict[str, Any]]) -> dict[str, Any]:
    proxy = {
        "vwap_20d": _vwap(bars, 20),
        "volume_vs_20d": None,
    }
    vols = [_volume(b)[0] or 0.0 for b in bars]
    if len(vols) >= 21 and sum(vols[-21:-1]) > 0:
        proxy["volume_vs_20d"] = round(vols[-1] / (sum(vols[-21:-1]) / 20), 3)

    if market != "CN":
        return {
            "degraded": True,
            "reason": "筹码分布仅覆盖 A 股（东财 CYQ）",
            "proxy": proxy,
        }

    primary = _akshare_primary()
    if primary is None:
        return {
            "degraded": True,
            "reason": "主数据源不是 AkShare，无法拉取筹码",
            "proxy": proxy,
        }
    try:
        rows = primary.fetch_chip_cyq(symbol)
    except Exception as exc:
        return {
            "degraded": True,
            "reason": _short_reason("筹码接口失败", exc),
            "proxy": proxy,
        }
    if not rows:
        return {
            "degraded": True,
            "reason": "筹码接口无数据",
            "proxy": proxy,
        }
    ranked = sorted(rows, key=lambda row: _parse_time(row.get("日期") or row.get("date")))
    latest = ranked[-1]
    return _chip_from_row(latest, last, bars)


def _flow_block(market: str, symbol: str) -> dict[str, Any]:
    if market != "CN":
        return {"degraded": True, "reason": "个股资金流向仅覆盖 A 股"}
    primary = _akshare_primary()
    if primary is None:
        return {"degraded": True, "reason": "主数据源不是 AkShare，无法拉取资金流"}
    try:
        rows = primary.fetch_fund_flow_rows(symbol, limit=12)
    except Exception as exc:
        return {"degraded": True, "reason": _short_reason("资金流接口失败", exc)}
    if not rows:
        return {"degraded": True, "reason": "资金流接口无数据"}
    ranked = sorted(rows, key=lambda r: _parse_time(r.get("日期") or r.get("date")), reverse=True)

    def _pick(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": str(row.get("日期") or row.get("date") or "")[:10],
            "main_net": _safe_float(row.get("主力净流入-净额") or row.get("主力净流入")),
            "main_net_pct": _safe_float(row.get("主力净流入-净占比")),
            "super_net": _safe_float(row.get("超大单净流入-净额")),
            "large_net": _safe_float(row.get("大单净流入-净额")),
        }

    def _sum_net(days: int) -> float | None:
        vals = [_pick(r)["main_net"] for r in ranked[:days]]
        present = [v for v in vals if v is not None]
        if not present:
            return None
        return round(sum(present), 2)

    latest = _pick(ranked[0])
    return {
        "degraded": False,
        "reason": None,
        "as_of": latest.get("date"),
        "latest": latest,
        "main_net_1d": latest.get("main_net"),
        "main_net_5d": _sum_net(5),
        "main_net_10d": _sum_net(10),
    }


def _snapshot_block(market: str, symbol: str) -> dict[str, Any]:
    if market == "CN":
        primary = _akshare_primary()
        if primary is None:
            return {"degraded": True, "reason": "主数据源不是 AkShare"}
        try:
            snap = primary.fetch_spot_snapshot(symbol)
        except Exception as exc:
            return {"degraded": True, "reason": _short_reason("个股快照失败", exc)}
        if not snap:
            return {"degraded": True, "reason": "个股快照无数据"}
        snap["degraded"] = False
        snap["reason"] = None
        return snap
    if market == "US":
        try:
            from backend.stock_domain.multi_providers import YFinanceMarketDataProvider

            yf = YFinanceMarketDataProvider()
            snap = yf.fetch_spot_snapshot(symbol)
            pos = yf.fetch_us_positioning(symbol)
        except Exception as exc:
            return {"degraded": True, "reason": _short_reason("美股快照失败", exc)}
        if not snap:
            return {"degraded": True, "reason": "美股快照无数据"}
        snap["degraded"] = False
        snap["reason"] = None
        snap["us_positioning"] = pos
        return snap
    if market == "HK":
        primary = _akshare_primary()
        if primary is None:
            return {"degraded": True, "reason": "主数据源不是 AkShare"}
        try:
            snap = primary.fetch_hk_spot_snapshot(symbol)
        except Exception as exc:
            return {"degraded": True, "reason": _short_reason("港股快照失败", exc)}
        if not snap:
            return {"degraded": True, "reason": "港股快照无数据"}
        snap["degraded"] = False
        snap["reason"] = None
        return snap
    return {"degraded": True, "reason": f"未知市场 {market}"}


def get_market_structure(symbol: str) -> dict[str, Any]:
    normalized = normalize_symbol(symbol)
    stock = get_stock(normalized)
    if not stock:
        return {
            "symbol": normalized,
            "degraded": True,
            "reason": f"unknown stock: {symbol}",
            "source": "unavailable",
            "updated_at": now_iso(),
            "technical": {"degraded": True, "reason": "unknown symbol", "missing": ["history"]},
            "snapshot": {"degraded": True, "reason": "unknown symbol"},
            "chip": {"degraded": True, "reason": "unknown symbol"},
            "flow": {"degraded": True, "reason": "unknown symbol"},
        }

    market = str(stock["market"])
    # 技术指标要逐日数据：detail 的瘦身默认只服务 agent 上下文，域内计算取全量。
    history = get_daily_history(normalized, 90, detail="full")
    hist_items = history.get("items") if isinstance(history, dict) else []
    if not isinstance(hist_items, list):
        hist_items = []
    technical = compute_technical(hist_items)
    bars = _bars_ascending(hist_items)
    last = technical.get("last") if not technical.get("degraded") else _safe_float(stock.get("price"))
    skip_chip_flow = _is_st_or_halted(stock) or _volume_dead(bars)
    snapshot = _snapshot_block(market, normalized)
    if skip_chip_flow and market == "CN":
        skip_reason = "ST/停牌或成交量长期为 0，跳过筹码与资金流"
        chip = {"degraded": True, "reason": skip_reason}
        flow = {"degraded": True, "reason": skip_reason}
    else:
        chip = _chip_block(market, normalized, last if isinstance(last, (int, float)) else None, bars)
        flow = _flow_block(market, normalized)

    extra = {
        "degraded": True,
        "reason": "北向/融资/龙虎榜/解禁未在本期接入",
        "missing": ["northbound", "margin", "lhb", "unlock"],
    }

    overall_degraded = bool(technical.get("degraded") and snapshot.get("degraded") and chip.get("degraded"))
    history_source = history.get("source") if isinstance(history, dict) else "unavailable"
    if history_source == "mock_adapter":
        history_source = "unavailable"
    return _json_safe(
        {
            "symbol": normalized,
            "name": stock.get("name"),
            "market": market,
            "source": history_source,
            "updated_at": now_iso(),
            "degraded": overall_degraded,
            "reason": technical.get("reason") if overall_degraded else None,
            "technical": technical,
            "snapshot": snapshot,
            "chip": chip,
            "flow": flow,
            "extra": extra,
        }
    )

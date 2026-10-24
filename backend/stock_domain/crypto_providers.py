"""加密货币行情（Gate.io 现货）。

为什么是 Gate.io：实测 Binance / OKX / Coinbase / CoinGecko 在大陆 ECS 与本地
**全部不可达**，只有 Gate.io 通（RTT 0.3–0.5s）。见 doc/CRYPTO_CAPABILITY_PLAN.md §0。

这个模块只做「取数」，不做 provider 接口那一整套（那是给 A/H/US 的）。
`provider_router` 对 market=CRYPTO 直接走这里，避免落到 akshare 上死等。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

GATE_BASE = "https://api.gateio.ws/api/v4"
QUOTE_TIMEOUT_SECONDS = 5
#: 加密货币 7×24 且波动快，报价缓存比 A 股短
QUOTE_TTL_SECONDS = 10
KLINE_TTL_SECONDS = 60

_lock = threading.RLock()
_quote_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _pair(symbol: str, quote: str = "USDT") -> str:
    return f"{str(symbol).strip().upper()}_{quote}"


#: 连续失败 N 次就熔断：Gate 挂了的时候不要让每次对话都等 5s 超时
BREAKER_THRESHOLD = 3
BREAKER_OPEN_SECONDS = 60
_breaker: dict[str, float] = {"failures": 0.0, "open_until": 0.0}


class CryptoSourceUnavailable(RuntimeError):
    """Gate 熔断中：直接降级，不再打源。"""


def breaker_state() -> dict[str, Any]:
    now = time.monotonic()
    return {
        "failures": int(_breaker["failures"]),
        "open": _breaker["open_until"] > now,
        "open_for_seconds": round(max(0.0, _breaker["open_until"] - now), 1),
        "threshold": BREAKER_THRESHOLD,
    }


def reset_breaker() -> None:
    _breaker["failures"] = 0.0
    _breaker["open_until"] = 0.0


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    import httpx

    now = time.monotonic()
    if _breaker["open_until"] > now:
        raise CryptoSourceUnavailable(
            f"Gate 连续失败已熔断，{breaker_state()['open_for_seconds']:.0f}s 后重试"
        )
    try:
        resp = httpx.get(f"{GATE_BASE}{path}", params=params, timeout=QUOTE_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        _breaker["failures"] += 1
        if _breaker["failures"] >= BREAKER_THRESHOLD:
            _breaker["open_until"] = now + BREAKER_OPEN_SECONDS
            _breaker["failures"] = 0
            logger.warning("gate breaker opened for %ss", BREAKER_OPEN_SECONDS)
        raise
    _breaker["failures"] = 0
    return data


def fetch_quote(symbol: str) -> dict[str, Any] | None:
    """返回 {last, change_pct, high_24h, low_24h, quote_volume, source}；失败抛异常。

    10 秒内存缓存：持仓页一次要取 N 个币，别每次都打源。
    """
    sym = str(symbol).strip().upper()
    now = time.monotonic()
    with _lock:
        hit = _quote_cache.get(sym)
        if hit is not None and now - hit[0] < QUOTE_TTL_SECONDS:
            return hit[1]
    try:
        rows = _get("/spot/tickers", {"currency_pair": _pair(sym)})
        row = (rows or [{}])[0] if isinstance(rows, list) else {}
        last = float(row.get("last") or 0)
        if last <= 0:
            raise ValueError(f"gate returned no price for {sym}")
        payload = {
            "symbol": sym,
            "last": last,
            "change_pct": float(row.get("change_percentage") or 0.0),
            "high_24h": float(row.get("high_24h") or 0.0) or None,
            "low_24h": float(row.get("low_24h") or 0.0) or None,
            "quote_volume": float(row.get("quote_volume") or 0.0) or None,
            "source": "gate_spot",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("gate quote failed for %s: %s", sym, exc)
        with _lock:
            _quote_cache[sym] = (now, None)  # 负缓存：短时间别反复打
        raise
    with _lock:
        _quote_cache[sym] = (now, payload)
    return payload


def fetch_klines(symbol: str, *, interval: str = "1d", limit: int = 60) -> list[dict[str, Any]]:
    """Gate K 线 → [{date, open, high, low, close, volume}]。

    Gate 返回 [时间戳, 计价量, 开, 高, 低, 收, 基础量, 是否收盘]。
    """
    rows = _get(
        "/spot/candlesticks",
        {"currency_pair": _pair(symbol), "interval": interval, "limit": int(limit)},
    )
    out: list[dict[str, Any]] = []
    from datetime import datetime, timezone

    for row in rows or []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        ts = int(row[0])
        out.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": float(row[6]),
            }
        )
    return out


def invalidate_cache() -> None:
    with _lock:
        _quote_cache.clear()


# ── 衍生品（永续）：资金费率 / 持仓量 / 多空比 / 清算 ────────────────
DERIVATIVES_TTL_SECONDS = 60
_deriv_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _percentile(values: list[float], target: float) -> float | None:
    """target 在 values 中的分位（0–100）。样本太少返回 None。"""
    clean = [v for v in values if v is not None]
    if len(clean) < 10:
        return None
    below = sum(1 for v in clean if v <= target)
    return round(below / len(clean) * 100, 1)


def fetch_derivatives(symbol: str) -> dict[str, Any]:
    """Gate 永续合约面。一次把「币圈的筹码」拿全。

    返回里的 percentile / annualized 都是**派生值**，原始字段一并给出，
    让模型自己判断，不要替它下结论。
    """
    sym = str(symbol).strip().upper()
    contract = f"{sym}_USDT"
    now = time.monotonic()
    with _lock:
        hit = _deriv_cache.get(sym)
        if hit is not None and now - hit[0] < DERIVATIVES_TTL_SECONDS:
            return hit[1]

    info = _get(f"/futures/usdt/contracts/{contract}")
    tickers = _get("/futures/usdt/tickers", {"contract": contract})
    funding_hist = _get("/futures/usdt/funding_rate", {"contract": contract, "limit": 90})
    stats = _get(
        "/futures/usdt/contract_stats", {"contract": contract, "interval": "1d", "limit": 2}
    )

    ticker = (tickers or [{}])[0] if isinstance(tickers, list) else {}
    rates = [
        float(row["r"]) for row in (funding_hist or []) if isinstance(row, dict) and "r" in row
    ]
    live_rate = float(ticker.get("funding_rate") or info.get("funding_rate_indicative") or 0)
    interval_seconds = int(info.get("funding_interval") or 28800)
    per_year = (365 * 24 * 3600) / max(interval_seconds, 1)

    latest_stat = (stats or [{}])[0] if isinstance(stats, list) else {}
    payload = {
        "symbol": sym,
        "contract": contract,
        "funding_rate": live_rate,
        "funding_rate_indicative": float(info.get("funding_rate_indicative") or 0),
        "funding_interval_hours": round(interval_seconds / 3600, 1),
        # 年化 = 单次费率 × 每年结算次数
        "funding_annualized_pct": round(live_rate * per_year * 100, 2),
        "funding_percentile_90d": _percentile(rates, live_rate),
        "funding_samples": len(rates),
        "mark_price": float(ticker.get("mark_price") or info.get("mark_price") or 0) or None,
        "index_price": float(info.get("index_price") or 0) or None,
        "maintenance_rate": float(info.get("maintenance_rate") or 0) or None,
        "open_interest_usd": float(latest_stat.get("open_interest") or 0) or None,
        "long_short_account_ratio": float(latest_stat.get("lsr_account") or 0) or None,
        "long_short_taker_ratio": float(latest_stat.get("lsr_taker") or 0) or None,
        "top_trader_long_short_ratio": float(latest_stat.get("top_lsr_size") or 0) or None,
        "liquidations_24h": {
            "long_usd": float(latest_stat.get("long_liq_usd") or 0) or None,
            "short_usd": float(latest_stat.get("short_liq_usd") or 0) or None,
        },
        "source": "gate_futures",
        "degraded": False,
    }
    with _lock:
        _deriv_cache[sym] = (now, payload)
    return payload


def invalidate_derivatives_cache() -> None:
    with _lock:
        _deriv_cache.clear()

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


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    import httpx

    resp = httpx.get(f"{GATE_BASE}{path}", params=params, timeout=QUOTE_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


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

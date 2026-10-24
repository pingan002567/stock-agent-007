"""加密货币**全市场**情绪数据（只给原始数据，不给结论）。

只给事实：总市值、24h 成交额、24h 市值变化、BTC/ETH 主导率、稳定币总量、
恐慌贪婪指数（当前值 / 英文分类 / 中文对照 / 前值）。
**不产出"该买 / 该卖 / 资金在躲 / 场外资金进场"这类结论** —— 那是模型的活，
和 `sentiment_tools.get_market_sentiment()`（A 股）的设计哲学一致。

数据来源（实测境内可达；Binance / OKX / Coinbase / CoinGecko 全部超时）：
- Coinlore `api/global`：`total_mcap` / `total_volume` / `mcap_change` / `btc_d` / `eth_d`
- DefiLlama `stablecoins`：所有稳定币 `circulating.peggedUSD` 之和
- alternative.me `fng`：恐慌贪婪指数（当前 + 前值）

纪律（与仓库其它工具一致）：
- 三个源**各自独立降级**：一个挂只影响它自己的字段，其它字段照常给出；
  失败只进 `coverage` 与 `degraded_reason`，**绝不把网络异常抛给调用方**。
- 拿不到就是 `None`，不猜、不编 0（稳定币空列表尤其不能当 0）。
- 缓存 5 分钟：全市场情绪不需要秒级刷新。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

COINLORE_GLOBAL_URL = "https://api.coinlore.net/api/global/"
DEFILLAMA_STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=2"

#: 情绪数据 5 分钟内不变，不必每次打三个源
CACHE_TTL_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 8

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_cache_at: float = 0.0


def _num(value: Any) -> float | None:
    """任何值 → float；拿不到就 None（不返回 0，避免把"缺数据"伪装成"零"）。"""
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _opt_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fear_greed_label_zh(value: int | None) -> str | None:
    """恐慌贪婪指数 → 中文对照（0-24 极度恐惧 / 25-44 恐惧 / 45-55 中性 / 56-75 贪婪 / 76-100 极度贪婪）。"""
    if value is None:
        return None
    if value <= 24:
        return "极度恐惧"
    if value <= 44:
        return "恐惧"
    if value <= 55:
        return "中性"
    if value <= 75:
        return "贪婪"
    return "极度贪婪"


def _get_json(url: str) -> Any:
    """取一个 JSON。测试里替换这个接缝即可，不必起 HTTP mock。"""
    import httpx

    resp = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


# ── 三个源：各自返回 (数据, 错误描述) ────────────────────────────────


def _fetch_global() -> tuple[dict[str, float | None], str | None]:
    """Coinlore 全市场：市值 / 24h 成交额 / 24h 市值变化 / BTC+ETH 主导率。"""
    try:
        payload = _get_json(COINLORE_GLOBAL_URL)
        # 正常是 [{...}]；个别镜像会直接给对象，两种都兼容
        rows = payload if isinstance(payload, list) else [payload]
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        if not row or row.get("total_mcap") is None:
            return {}, "Coinlore 全市场数据为空"
        return {
            "total_market_cap_usd": _num(row.get("total_mcap")),
            "total_volume_24h_usd": _num(row.get("total_volume")),
            "market_cap_change_24h_pct": _num(row.get("mcap_change")),
            "btc_dominance_pct": _num(row.get("btc_d")),
            "eth_dominance_pct": _num(row.get("eth_d")),
        }, None
    except Exception as exc:  # noqa: BLE001 - 外部源什么都可能抛
        logger.warning("coinlore global failed: %s", exc)
        return {}, f"Coinlore 全市场源不可用（{type(exc).__name__}）"


def _fetch_stablecoin_total() -> tuple[float | None, str | None]:
    """DefiLlama 稳定币总流通量（所有 `circulating.peggedUSD` 求和）。"""
    try:
        payload = _get_json(DEFILLAMA_STABLECOINS_URL)
        assets = payload.get("peggedAssets") if isinstance(payload, dict) else None
        if not isinstance(assets, list):
            return None, "DefiLlama 稳定币数据格式异常"
        total = 0.0
        sampled = 0
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            circulating = asset.get("circulating")
            amount = _num(circulating.get("peggedUSD")) if isinstance(circulating, dict) else None
            if amount is None:
                continue
            total += amount
            sampled += 1
        if not sampled:
            # 空列表 / 全部缺字段：总量未知，不能返回 0
            return None, "DefiLlama 稳定币数据为空"
        return total, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("defillama stablecoins failed: %s", exc)
        return None, f"DefiLlama 稳定币源不可用（{type(exc).__name__}）"


def _fetch_fear_greed() -> tuple[dict[str, Any], str | None]:
    """alternative.me 恐慌贪婪指数：当前值 + 英文分类 + 前值（limit=2 的第二条）。"""
    try:
        payload = _get_json(FEAR_GREED_URL)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return {
                "value": None,
                "label_en": None,
                "label_zh": None,
                "previous": None,
            }, "alternative.me 恐贪数据为空"
        current = rows[0]
        value = _opt_int(current.get("value"))
        previous = _opt_int(rows[1].get("value")) if len(rows) > 1 and isinstance(rows[1], dict) else None
        return {
            "value": value,
            "label_en": str(current.get("value_classification") or "").strip() or None,
            "label_zh": _fear_greed_label_zh(value),
            "previous": previous,
        }, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("alternative.me fear&greed failed: %s", exc)
        return {
            "value": None,
            "label_en": None,
            "label_zh": None,
            "previous": None,
        }, f"alternative.me 恐贪源不可用（{type(exc).__name__}）"


def _coverage_entry(error: str | None, fields: list[str]) -> dict[str, Any]:
    return {"status": "failed" if error else "ok", "error": error, "fields": fields}


def get_crypto_market_sentiment() -> dict[str, Any]:
    """加密货币全市场情绪原始数据：市值 / 主导率 / 稳定币总量 / 恐慌贪婪。

    只做**聚合**（求和、取字段），不做**判断**（不写情绪阶段、资金流向结论）。
    三个源独立降级：任一失败只置它自己的字段为 None，其它字段照常返回。
    """
    global _cache, _cache_at
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache_at < CACHE_TTL_SECONDS:
            return _cache

    market, market_error = _fetch_global()
    stablecoin_total, stablecoin_error = _fetch_stablecoin_total()
    fear_greed, fear_greed_error = _fetch_fear_greed()

    errors = [e for e in (market_error, stablecoin_error, fear_greed_error) if e]
    payload: dict[str, Any] = {
        "market": "CRYPTO",
        "total_market_cap_usd": market.get("total_market_cap_usd"),
        "total_volume_24h_usd": market.get("total_volume_24h_usd"),
        "market_cap_change_24h_pct": market.get("market_cap_change_24h_pct"),
        "btc_dominance_pct": market.get("btc_dominance_pct"),
        "eth_dominance_pct": market.get("eth_dominance_pct"),
        "stablecoin_total_usd": stablecoin_total,
        "fear_greed": fear_greed,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "market": "coinlore",
            "stablecoin": "defillama",
            "fear_greed": "alternative.me",
        },
        "degraded": bool(errors),
        "degraded_reason": "；".join(errors) if errors else None,
        "coverage": {
            "coinlore": _coverage_entry(
                market_error,
                [
                    "total_market_cap_usd",
                    "total_volume_24h_usd",
                    "market_cap_change_24h_pct",
                    "btc_dominance_pct",
                    "eth_dominance_pct",
                ],
            ),
            "defillama": _coverage_entry(stablecoin_error, ["stablecoin_total_usd"]),
            "alternative_me": _coverage_entry(
                fear_greed_error,
                ["fear_greed.value", "fear_greed.label_en", "fear_greed.label_zh", "fear_greed.previous"],
            ),
        },
    }
    with _lock:
        _cache = payload
        _cache_at = now
    return payload


def invalidate_cache() -> None:
    """清空模块级缓存（测试 / 手动刷新用）。"""
    global _cache, _cache_at
    with _lock:
        _cache = None
        _cache_at = 0.0

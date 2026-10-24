"""汇率服务：把外币持仓折算成人民币。

口径（2026-10-24 定）：
- **按当天汇率折算**，且**折算结果不落库** —— 存下来等于把汇率冻死，
  第二天汇率变了总资产却不变，是错的。
- 汇率**按日缓存**：同一天复用同一份，跨零点自动重取。日内可手动刷新。

数据源：open.er-api.com（免 key，实测大陆 ECS 可达）。
USDT 按 USD 1:1 处理（脱锚检测留到阶段二，届时接 Gate 的 USDC/USDT 价差）。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: 主源：免 key、含 CNY/HKD
FX_SOURCE = "https://open.er-api.com/v6/latest/USD"
#: 备源：ECB 数据（frankfurter 会 301 到 api.frankfurter.dev，必须跟随重定向）
FX_FALLBACK_SOURCE = "https://api.frankfurter.app/latest?from=USD&to=CNY,HKD"
FX_TIMEOUT_SECONDS = 8

#: 我们支持的币种 → 这里存「1 单位该币 = ? CNY」
SUPPORTED_CURRENCIES: tuple[str, ...] = ("CNY", "HKD", "USD", "USDT")

#: 退路：网络全挂时用的备用汇率（**只在显式允许时使用**，默认不用）
_FALLBACK_RATES: dict[str, float] = {"USD": 6.68, "HKD": 0.86}

_lock = threading.RLock()
_cache: dict[str, Any] = {"day": None, "payload": None}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _fetch_primary() -> tuple[float, float, str]:
    """主源 open.er-api.com → (usd_cny, usd_hkd, source)。"""
    import httpx

    resp = httpx.get(FX_SOURCE, timeout=FX_TIMEOUT_SECONDS, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("result") or "").lower() != "success":
        raise ValueError(f"fx source returned result={data.get('result')!r}")
    rates = data.get("rates") or {}
    usd_cny = float(rates.get("CNY") or 0)
    usd_hkd = float(rates.get("HKD") or 0)
    if usd_cny <= 0:
        raise ValueError("fx source missing CNY rate")
    return usd_cny, usd_hkd, "open.er-api.com"


def _fetch_fallback() -> tuple[float, float, str]:
    """备源 frankfurter（ECB）→ (usd_cny, usd_hkd, source)。"""
    import httpx

    resp = httpx.get(
        FX_FALLBACK_SOURCE, timeout=FX_TIMEOUT_SECONDS, follow_redirects=True
    )
    resp.raise_for_status()
    data = resp.json()
    rates = data.get("rates") or {}
    usd_cny = float(rates.get("CNY") or 0)
    usd_hkd = float(rates.get("HKD") or 0)
    if usd_cny <= 0:
        raise ValueError("fx fallback missing CNY rate")
    return usd_cny, usd_hkd, "frankfurter.app"


def _fetch_rates() -> dict[str, Any]:
    """主源 → 备源 → 降级。两个源都挂才算降级。"""
    errors: list[str] = []
    usd_cny = usd_hkd = 0.0
    source = ""
    for fetcher in (_fetch_primary, _fetch_fallback):
        try:
            usd_cny, usd_hkd, source = fetcher()
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fetcher.__name__}:{type(exc).__name__}")
            logger.warning("fx %s failed: %s", fetcher.__name__, exc)
            continue
    if usd_cny <= 0:
        raise ValueError("no fx source available: " + ", ".join(errors))

    # 1 HKD 值多少 CNY = (CNY per USD) / (HKD per USD)
    hkd_cny = round(usd_cny / usd_hkd, 6) if usd_hkd > 0 else 0.0
    return {
        "as_of": _today(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "usd_cny": round(usd_cny, 6),
        "hkd_cny": hkd_cny,
        "usdt_usd": 1.0,
        "degraded": False,
        "degraded_reason": None,
    }


def _degraded_payload(reason: str) -> dict[str, Any]:
    return {
        "as_of": _today(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "open.er-api.com",
        "usd_cny": None,
        "hkd_cny": None,
        "usdt_usd": None,
        "degraded": True,
        "degraded_reason": reason[:200],
    }


def get_rates(*, refresh: bool = False) -> dict[str, Any]:
    """当日汇率（按日缓存；refresh=True 强制重取）。"""
    today = _today()
    with _lock:
        cached = _cache.get("payload")
        if (
            not refresh
            and cached is not None
            and _cache.get("day") == today
            # 降级结果不缓存一整天：允许下一次请求再试
            and not cached.get("degraded")
        ):
            return dict(cached)
    try:
        payload = _fetch_rates()
    except Exception as exc:  # noqa: BLE001 - 网络/解析什么都可能抛
        logger.warning("fx fetch failed: %s", exc)
        payload = _degraded_payload(f"汇率源不可用：{type(exc).__name__}")
    with _lock:
        _cache["day"] = today
        _cache["payload"] = payload
    return dict(payload)


def rates_for_conversion(payload: dict[str, Any] | None = None) -> dict[str, float] | None:
    """返回 {币种: 折算成 CNY 的系数}；降级时返回 None（调用方必须显示 —，不能按 1:1 硬算）。"""
    data = payload if payload is not None else get_rates()
    if data.get("degraded") or not data.get("usd_cny"):
        return None
    usd_cny = float(data["usd_cny"])
    usdt_usd = float(data.get("usdt_usd") or 1.0)
    return {
        "CNY": 1.0,
        "USD": usd_cny,
        "HKD": float(data.get("hkd_cny") or 0.0),
        "USDT": usd_cny * usdt_usd,
    }


def to_cny(amount: float, currency: str, rates: dict[str, float] | None) -> float | None:
    """把原币金额折算成人民币；无汇率返回 None（**不要退化成原值或 0**）。"""
    if rates is None:
        return None
    rate = rates.get(str(currency or "CNY").upper())
    if rate is None:
        return None
    return round(float(amount or 0) * rate, 2)


def invalidate_cache() -> None:
    with _lock:
        _cache["day"] = None
        _cache["payload"] = None

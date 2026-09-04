from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, TypeVar

from backend.app_services.runtime_observer import runtime_observer
from backend.config.data_sources import DEFAULT_DATA_SOURCES
from backend.config.provider_policy import (
    is_provider_usable,
    resolve_market_provider,
    selectable_providers_for_market,
)
from backend.schemas import PriceSnapshot, StockDaily, StockQuote, now_iso
from backend.stock_domain.catalog import get_stock, normalize_symbol
from backend.stock_domain.multi_providers import create_provider
from backend.stock_domain.provider_cache import ProviderCache
from backend.stock_domain.trading_calendar import prev_trading_day
from backend.stock_domain.providers import (
    AkShareMarketDataProvider,
    DataCapabilityStatus,
    MarketDataProvider,
    MockMarketDataProvider,
    ProviderStatus,
)

T = TypeVar("T")

_NO_MOCK_CAPABILITIES = frozenset({"quote", "history", "intel", "financial", "chip", "fund_flow", "snapshot"})

# Layer 1 memory cache TTL per capability (seconds)
_CACHE_TTL: dict[str, float] = {
    "quote": 60.0,      # 60s during trading hours
    "history": 600.0,   # 10min (primary cache is SQLite)
    "intel": 600.0,     # 10min
    "market": 300.0,    # 5min
    "sectors": 300.0,   # 5min
    "financial": 3600.0, # 1h
}

# SQLite cache TTL: how long to trust persisted data before refreshing from API
_SQLITE_CACHE_TTL: dict[str, float] = {
    "quote": 120.0,     # 2min from SQLite during trading, unlimited after hours
    "history": 86400.0,  # K-line is immutable: trust SQLite for 24h
    "financial": 604800.0, # 7 days
}


def _is_trading_hours(market: str) -> bool:
    """Check if we're currently in trading hours for the given market."""
    now = datetime.now()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    if market == "CN" or market is None:
        return 9 <= now.hour < 15 or (now.hour == 9 and now.minute >= 30)
    if market == "US":
        et_offset = -4  # EDT, simplified
        et_hour = (now.hour + et_offset) % 24
        return 9 <= et_hour < 16
    return True  # unknown market: always consider trading


@dataclass
class _CircuitBreakerState:
    failures: int = 0
    last_failure_at: float = 0.0
    state: str = "closed"  # closed / open / half-open


class ProviderRouter:
    def __init__(
        self,
        primary: MarketDataProvider | None = None,
        fallback: MockMarketDataProvider | None = None,
    ) -> None:
        self.primary = primary or AkShareMarketDataProvider()
        self.fallback = fallback or MockMarketDataProvider()
        self.repo: Any = None
        self._last_degraded_reason: str | None = None
        self._last_capability_reasons: dict[str, str | None] = {
            "quote": None,
            "history": None,
            "intel": None,
            "market": None,
            "sectors": None,
            "financial": None,
        }
        # Cache of provider instances by id: {"akshare": <AkShareMarketDataProvider>, ...}
        self._provider_instances: dict[str, MarketDataProvider] = {}
        # Per-capability circuit breaker: prevents repeated futile primary calls
        self._circuit_breakers: dict[str, _CircuitBreakerState] = {
            cap: _CircuitBreakerState()
            for cap in ["quote", "history", "intel", "market", "sectors", "financial"]
        }
        self._circuit_breaker_threshold = 3  # consecutive failures before opening
        self._circuit_breaker_timeout = 30.0  # seconds before half-open probe
        self._mem_cache = ProviderCache(maxsize=4096)
        self._last_warmup: float = 0.0

    def clear_cache(self, market: str | None = None) -> None:
        """Clear provider instances and memory cache.
        
        Args:
            market: If specified, only clear cache for that market's provider.
                    If None, clear all caches.
        """
        if market:
            provider_id = self._provider_id_for_market(market)
            self._provider_instances.pop(provider_id, None)
            self._mem_cache.invalidate_prefix(f"{market}:")
        else:
            self._provider_instances.clear()
            self._mem_cache.invalidate_prefix("")
        # Reset circuit breakers
        for cb in self._circuit_breakers.values():
            cb.failures = 0
            cb.state = "closed"

    def _data_sources_config(self) -> dict:
        if not self.repo:
            return DEFAULT_DATA_SOURCES
        try:
            return self.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
        except Exception:
            return DEFAULT_DATA_SOURCES

    def _provider_id_for_market(self, market: str | None) -> str:
        if not market:
            return "eastmoney"
        try:
            return resolve_market_provider(self._data_sources_config(), market)
        except Exception:
            return "eastmoney" if market != "US" else "yfinance"

    def _resolve_provider_id(self, provider_id: str, market: str | None) -> str:
        if provider_id == "mock":
            if market == "US":
                return "yfinance"
            return "eastmoney"
        return provider_id

    def _get_provider(self, provider_id: str, market: str | None = None) -> MarketDataProvider:
        """Get or create a provider instance by id."""
        provider_id = self._resolve_provider_id(provider_id, market)
        config = self._data_sources_config()
        if not is_provider_usable(config, provider_id):
            if market:
                fallback_id = resolve_market_provider(config, market)
                if fallback_id != provider_id and is_provider_usable(config, fallback_id):
                    provider_id = fallback_id
        if provider_id in self._provider_instances:
            return self._provider_instances[provider_id]
        instance = create_provider(provider_id)
        self._provider_instances[provider_id] = instance
        return instance

    def _provider_for_market(self, market: str | None) -> MarketDataProvider:
        """Resolve the configured provider for a market."""
        provider_id = self._provider_id_for_market(market)
        return self._get_provider(provider_id, market)

    def _secondary_providers(
        self, market: str | None, primary: MarketDataProvider
    ) -> list[MarketDataProvider]:
        """Get additional providers to try before falling back to Mock.

        Returns an ordered list of providers to attempt after the primary fails.
        These serve as cross-provider fallbacks — e.g. for US: yfinance → akshare → mock.
        """
        config = self._data_sources_config()
        chain: list[MarketDataProvider] = []
        if not market:
            return chain
        for pid in selectable_providers_for_market(config, market):
            if pid == primary.name:
                continue
            try:
                p = self._get_provider(pid, market)
                if p.is_available():
                    chain.append(p)
            except Exception:
                continue
        return chain

    def status(self) -> ProviderStatus:
        primary_available = self.primary.is_available()
        capabilities = {
            "quote": self._circuit_capability_status("quote"),
            "history": self._circuit_capability_status("history"),
            "intel": self._circuit_capability_status("intel"),
            "market": self._circuit_capability_status("market"),
            "sectors": self._circuit_capability_status("sectors"),
            "financial": self._circuit_capability_status("financial"),
        }
        degraded = any(item.degraded for item in capabilities.values())
        degraded_reason = next(
            (
                item.degraded_reason
                for item in capabilities.values()
                if item.degraded_reason
            ),
            None,
        )
        return ProviderStatus(
            akshare_available=primary_available,
            active_provider=self.fallback.name if degraded else self.primary.name,
            fallback_provider=self.fallback.name,
            degraded=degraded,
            degraded_reason=degraded_reason,
            capabilities=capabilities,
        )

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        ck = self._cache_key("quote", normalized)
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        market = self._market_of(normalized)
        trading = _is_trading_hours(market)
        sqlite_age_limit = _SQLITE_CACHE_TTL["quote"] if trading else _SQLITE_CACHE_TTL["history"]
        if self.repo is not None:
            try:
                cached = self.repo.get_stock_quote(normalized)
                if cached is not None and cached.updated_at and (cached.last or 0) > 0:
                    cache_time = datetime.fromisoformat(cached.updated_at)
                    age = (datetime.now(timezone.utc) - cache_time).total_seconds()
                    if age < sqlite_age_limit:
                        result = PriceSnapshot(
                            last=cached.last, change_pct=cached.change_pct or 0.0,
                            updated_at=cached.updated_at, source=cached.source,
                            degraded=False,
                            coverage={"source": "sqlite_cache", "mode": "persisted", "cached_at": cached.updated_at},
                        )
                        self._mem_cache.set(ck, result, ttl=_CACHE_TTL["quote"])
                        return result
            except Exception:
                pass
        # cache miss: fetch live (with provider fallback chain)
        provider = self._provider_for_market(market)
        result = self._call_with_provider(
            "quote",
            provider,
            market,
            lambda p: p.get_quote(normalized),
            symbol=normalized,
        )
        if isinstance(result, PriceSnapshot) and not result.degraded:
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["quote"])
        return result

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        market = self._market_of(normalized)
        ck = self._cache_key("history", normalized, days=str(days))
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        if self.repo is not None:
            newest = self.repo.list_stock_daily(normalized, limit=1)
            if newest:
                raw_date = (newest[0].trade_date or "").strip()
                if raw_date:
                    if " " in raw_date:
                        raw_date = raw_date.split(" ")[0]
                    try:
                        newest_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                        trading_day_diff = (date.today() - newest_date).days
                        cached_count = self.repo.count_stock_daily(normalized)
                        if cached_count >= days and trading_day_diff <= 3:
                            items = []
                            for r in self.repo.list_stock_daily(normalized, limit=days):
                                volume = float(r.volume or 0)
                                amount = float(r.amount or 0)
                                close = float(r.close or 0)
                                if volume <= 0 and amount > 0 and close > 0:
                                    volume = round(amount / close, 0)
                                items.append({
                                    "day": 0,
                                    "date": r.trade_date,
                                    "open": r.open,
                                    "high": r.high,
                                    "low": r.low,
                                    "close": close,
                                    "volume": volume,
                                    "amount": amount,
                                })
                            items.reverse()
                            for idx, item in enumerate(items):
                                item["day"] = idx + 1
                            stale_volumes = (
                                bool(items)
                                and all(float(i.get("volume") or 0) <= 0 for i in items)
                                and any(float(i.get("amount") or 0) > 0 for i in items)
                            )
                            if not stale_volumes:
                                result = {
                                    "symbol": normalized,
                                    "source": "cache",
                                    "updated_at": now_iso(),
                                    "degraded": False,
                                    "degraded_reason": None,
                                    "coverage": {"source": "sqlite_cache", "mode": "persisted"},
                                    "items": items,
                                }
                                self._mem_cache.set(ck, result, ttl=_CACHE_TTL["history"])
                                return result
                    except ValueError:
                        pass
        provider = self._provider_for_market(market)
        result = self._call_with_provider(
            "history",
            provider,
            market,
            lambda p: p.get_history(normalized, days),
            symbol=normalized,
        )
        if isinstance(result, dict) and not result.get("degraded"):
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["history"])
        return result

    def search_intel(self, symbol: str, query: str = "") -> dict:
        normalized = normalize_symbol(symbol)
        market = self._market_of(normalized)
        ck = self._cache_key("intel", normalized, query=query)
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        provider = self._provider_for_market(market)
        result = self._call_with_provider(
            "intel",
            provider,
            market,
            lambda p: p.search_intel(normalized, query),
        )
        if isinstance(result, dict) and not result.get("degraded"):
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["intel"])
        return result

    def get_market_review(self) -> dict:
        ck = self._cache_key("market")
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        provider = self._provider_for_market("CN")
        result = self._call_with_provider(
            "market",
            provider,
            "CN",
            lambda p: p.get_market_review(),
        )
        if isinstance(result, dict) and not result.get("degraded"):
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["market"])
        return result

    def get_sectors(self) -> dict:
        ck = self._cache_key("sectors")
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        provider = self._provider_for_market("CN")
        result = self._call_with_provider(
            "sectors",
            provider,
            "CN",
            lambda p: p.get_sectors(),
        )
        if isinstance(result, dict) and not result.get("degraded"):
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["sectors"])
        return result

    def get_market_timeline(self) -> list[dict]:
        provider = self._provider_for_market("CN")
        return self._call_with_provider(
            "market",
            provider,
            "CN",
            lambda p: p.get_market_timeline(),
        )

    def get_financial(self, symbol: str) -> dict:
        normalized = normalize_symbol(symbol)
        market = self._market_of(normalized)
        ck = self._cache_key("financial", normalized)
        cached = self._mem_cache.get(ck)
        if cached is not None:
            return cached
        provider = self._provider_for_market(market)
        result = self._call_with_provider(
            "financial",
            provider,
            market,
            lambda p: p.get_financial(normalized),
            symbol=normalized,
        )
        if isinstance(result, dict) and not result.get("degraded"):
            self._mem_cache.set(ck, result, ttl=_CACHE_TTL["financial"])
        return result

    def invalidate_cache(self, capability: str, symbol: str = "", **extra: str) -> None:
        if symbol:
            self._mem_cache.invalidate(self._cache_key(capability, symbol, **extra))
        else:
            self._mem_cache.invalidate_prefix(f"{capability}:")

    def warmup_hot_stocks(self, symbols: list[str] | None = None) -> None:
        """Pre-fetch quotes for hot stocks. Gated: skips if warmed < 4 hours ago."""
        now = time.monotonic()
        if now - self._last_warmup < 14400:  # 4 hours
            return
        self._last_warmup = now
        if symbols is None:
            if self.repo is not None:
                try:
                    masters = self.repo.list_stock_master(active_only=True)
                    symbols = [m.symbol for m in masters]
                except Exception:
                    return
        if not symbols:
            return
        import logging as _log

        _log.getLogger("provider_router").info(
            "warming up %d hot stocks …", len(symbols[:20])
        )
        for symbol in symbols[:5]:
            try:
                self.get_quote(symbol)
            except Exception:
                pass

    def _is_circuit_open(self, capability: str) -> bool:
        cb = self._circuit_breakers[capability]
        if cb.state == "closed":
            return False
        if cb.state == "open":
            if time.monotonic() - cb.last_failure_at >= self._circuit_breaker_timeout:
                cb.state = "half-open"
                return False
            return True
        # half-open: allow one probe request
        return False

    def _record_success(self, capability: str) -> None:
        cb = self._circuit_breakers[capability]
        cb.failures = 0
        cb.state = "closed"

    def _record_failure(self, capability: str) -> None:
        cb = self._circuit_breakers[capability]
        cb.failures += 1
        cb.last_failure_at = time.monotonic()
        if cb.failures >= self._circuit_breaker_threshold:
            cb.state = "open"

    def _circuit_capability_status(self, capability: str) -> DataCapabilityStatus:
        base = self._capability_status(capability, self.primary.is_available())
        cb = self._circuit_breakers[capability]
        base.circuit_state = cb.state
        base.circuit_failures = cb.failures
        return base

    def _call_with_provider(
        self,
        capability: str,
        provider: MarketDataProvider,
        market: str | None,
        call_fn: Callable[[MarketDataProvider], T],
        symbol: str = "",
    ) -> T:
        """Execute a capability call with the given provider, falling back on failure."""
        started = time.perf_counter()

        # If the configured provider is mock, go straight to fallback
        if provider is self.fallback:
            result = call_fn(provider)
            self._record_call(
                capability=capability,
                market=market,
                provider=provider.name,
                status="configured",
                degraded_reason=f"market {market} configured to use {provider.name}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return result

        # Circuit breaker: skip primary if circuit is open, go directly to fallback
        if self._is_circuit_open(capability):
            reason = (
                f"circuit breaker open for {capability} "
                f"after {self._circuit_breakers[capability].failures} consecutive failures"
            )
            fallback_result = self._fallback_payload(
                capability, symbol, reason, call_fn
            )
            payload = fallback_result
            self._last_capability_reasons[capability] = reason
            self._refresh_last_degraded_reason()
            self._record_call(
                capability=capability,
                market=market,
                provider="unavailable"
                if capability in _NO_MOCK_CAPABILITIES
                else self.fallback.name,
                status="circuit_open",
                degraded_reason=reason,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return payload

        try:
            result = call_fn(provider)
            self._record_success(capability)
            self._last_capability_reasons[capability] = None
            self._refresh_last_degraded_reason()
            self._record_call(
                capability=capability,
                market=market,
                provider=provider.name,
                status="succeeded",
                degraded_reason=None,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            self._persist_result(
                capability, result, symbol, provider_name=provider.name
            )
            return result
        except Exception as exc:
            retry_delays = [0.5, 1.0]
            last_exc = exc
            for idx, delay in enumerate(retry_delays):
                time.sleep(delay)
                try:
                    started = time.perf_counter()
                    result = call_fn(provider)
                    self._record_success(capability)
                    self._last_capability_reasons[capability] = None
                    self._refresh_last_degraded_reason()
                    self._record_call(
                        capability=capability,
                        market=market,
                        provider=provider.name,
                        status="succeeded-after-retry",
                        degraded_reason=None,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                    self._persist_result(
                        capability, result, symbol, provider_name=provider.name
                    )
                    return result
                except Exception as retry_exc:
                    last_exc = retry_exc
            self._record_failure(capability)
            # Try secondary providers before falling back to Mock
            secondary_providers = self._secondary_providers(market, provider)
            for secondary in secondary_providers:
                try:
                    secondary_started = time.perf_counter()
                    result = call_fn(secondary)
                    self._record_success(capability)
                    secondary_reason = (
                        f"{provider.name} failed ({last_exc}), "
                        f"resolved by {secondary.name}"
                    )
                    self._last_capability_reasons[capability] = secondary_reason
                    self._refresh_last_degraded_reason()
                    self._record_call(
                        capability=capability,
                        market=market,
                        provider=secondary.name,
                        status="secondary",
                        degraded_reason=secondary_reason,
                        duration_ms=(time.perf_counter() - secondary_started) * 1000,
                    )
                    self._persist_result(
                        capability, result, symbol, provider_name=secondary.name
                    )
                    return self._degraded(result, secondary_reason)
                except Exception:
                    continue
            reason = f"{provider.name}: {last_exc}"
            self._last_capability_reasons[capability] = reason
            self._refresh_last_degraded_reason()
            payload = self._fallback_payload(capability, symbol, reason, call_fn)
            self._record_call(
                capability=capability,
                market=market,
                provider="unavailable"
                if capability in _NO_MOCK_CAPABILITIES
                else self.fallback.name,
                status="fallback",
                degraded_reason=reason,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return payload

    def _unavailable_payload(
        self, capability: str, symbol: str, reason: str
    ) -> Any:
        if capability == "quote":
            return PriceSnapshot(
                last=0.0,
                change_pct=0.0,
                updated_at=now_iso(),
                source="unavailable",
                degraded=True,
                degraded_reason=reason,
                coverage={"mode": "unavailable"},
            )
        payload: dict[str, Any] = {
            "symbol": symbol.upper() if symbol else "",
            "source": "unavailable",
            "updated_at": now_iso(),
            "degraded": True,
            "degraded_reason": reason,
            "coverage": {"mode": "unavailable"},
            "items": [],
        }
        if capability == "intel":
            payload["query"] = ""
        return payload

    def _fallback_payload(
        self, capability: str, symbol: str, reason: str, call_fn: Callable[[MarketDataProvider], T]
    ) -> T:
        if capability in _NO_MOCK_CAPABILITIES:
            return self._unavailable_payload(capability, symbol, reason)
        fallback_result = call_fn(self.fallback)
        return self._degraded(fallback_result, reason)

    def _degraded(self, payload: T, reason: str) -> T:
        if isinstance(payload, PriceSnapshot):
            payload.degraded = True
            payload.degraded_reason = reason
            return payload
        if isinstance(payload, dict):
            payload["degraded"] = True
            payload["degraded_reason"] = reason
        return payload

    def _market_of(self, symbol: str) -> str | None:
        stock = get_stock(symbol)
        return str(stock["market"]) if stock else None

    def _capability_status(
        self, capability: str, primary_available: bool
    ) -> DataCapabilityStatus:
        reason = self._last_capability_reasons.get(capability)
        degraded = reason is not None or not primary_available
        return DataCapabilityStatus(
            capability=capability,
            active_provider=self.fallback.name if degraded else self.primary.name,
            degraded=degraded,
            degraded_reason=reason
            or (self._fallback_reason() if not primary_available else None),
        )

    def _refresh_last_degraded_reason(self) -> None:
        self._last_degraded_reason = next(
            (reason for reason in self._last_capability_reasons.values() if reason),
            None,
        )

    def _fallback_reason(self) -> str:
        return f"{self.primary.name} optional dependency is not installed"

    def _cache_key(self, capability: str, symbol: str = "", **extra: str) -> str:
        parts = [capability]
        if symbol:
            parts.append(symbol)
        for k, v in sorted(extra.items()):
            parts.append(f"{k}={v}")
        return ":".join(parts)

    def _persist_result(
        self, capability: str, result: Any, symbol: str = "", provider_name: str = ""
    ) -> None:
        repo = self.repo
        if repo is None:
            return
        try:
            if (
                capability == "quote"
                and isinstance(result, PriceSnapshot)
                and not result.degraded
            ):
                repo.upsert_stock_quote(
                    StockQuote(
                        symbol=symbol,
                        last=result.last,
                        change_pct=result.change_pct,
                        source=result.source,
                        provider=provider_name,
                        updated_at=result.updated_at or now_iso(),
                    )
                )
            elif (
                capability == "history"
                and isinstance(result, dict)
                and not result.get("degraded")
            ):
                items = result.get("items", [])
                if items:
                    batch = [
                        StockDaily(
                            symbol=symbol,
                            trade_date=str(item.get("date", "")),
                            open=float(item.get("open", 0)),
                            high=float(item.get("high", 0)),
                            low=float(item.get("low", 0)),
                            close=float(item.get("close", 0)),
                            volume=float(item.get("volume", 0)),
                            amount=float(item.get("amount", 0)),
                            source=result.get("source", ""),
                        )
                        for item in items
                    ]
                    repo.batch_upsert_stock_daily(batch)
            elif (
                capability == "financial"
                and isinstance(result, dict)
                and not result.get("degraded")
            ):
                from backend.schemas import StockFinancial

                items = result.get("items", [])
                for item in items:
                    repo.upsert_stock_financial(
                        StockFinancial(
                            symbol=symbol,
                            report_date=str(item.get("report_date", "")),
                            report_type=str(item.get("report_type", "annual")),
                            revenue=float(item.get("revenue", 0)),
                            profit=float(item.get("profit", 0)),
                            total_assets=float(item.get("total_assets", 0)),
                            total_liabilities=float(item.get("total_liabilities", 0)),
                            payload={
                                "source": result.get("source", ""),
                                "coverage": result.get("coverage"),
                            },
                        )
                    )
            elif (
                capability in {"market", "sectors", "intel"}
                and isinstance(result, dict)
                and not result.get("degraded")
            ):
                repo.upsert_capability_cache(capability, result, symbol=symbol)
        except Exception:
            import logging

            logging.getLogger("provider_router").exception(
                "persist failed for %s", capability
            )

    def _record_call(
        self,
        *,
        capability: str,
        market: str | None,
        provider: str,
        status: str,
        degraded_reason: str | None,
        duration_ms: float,
    ) -> None:
        runtime_observer.record_provider_call(
            capability=capability,
            market=market,
            symbol=None,
            provider=provider,
            fallback_provider=self.fallback.name,
            status=status,
            degraded_reason=degraded_reason,
            duration_ms=round(duration_ms, 2),
        )


provider_router = ProviderRouter()

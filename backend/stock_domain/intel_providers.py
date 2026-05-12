from __future__ import annotations

import time
from typing import Any, Protocol

from backend.schemas import now_iso
from backend.stock_domain.catalog import get_stock, normalize_symbol


class IntelProvider(Protocol):
    name: str

    def search_news(self, symbol: str, query: str = "") -> dict:
        ...


class MockIntelProvider:
    name = "mock"

    def search_news(self, symbol: str, query: str = "") -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        name = stock["name"] if stock else symbol
        items: list[dict[str, Any]] = [
            {"type": "news", "title": f"{name} 近期股价波动，市场关注度提升", "source": "mock_news", "confidence": "medium", "published_at": now_iso()},
            {"type": "news", "title": f"{name} 所在板块获机构增持评级", "source": "mock_news", "confidence": "medium", "published_at": now_iso()},
            {"type": "news", "title": f"{name} 发布最新经营数据公告", "source": "mock_filing", "confidence": "medium", "published_at": now_iso()},
        ]
        return {
            "symbol": normalized,
            "query": query,
            "source": self.name,
            "updated_at": now_iso(),
            "items": items,
            "coverage": {"mode": "mock"},
        }


class AkShareIntelProvider:
    """Wraps the existing AKShare intel logic from AkShareMarketDataProvider.

    This reuses akshare's search_intel which aggregates profile, holders,
    financials, fund flow, and news from multiple AKShare endpoints.
    """

    name = "akshare"

    def __init__(self) -> None:
        self._delegate: Any = None

    def _get_delegate(self):
        if self._delegate is None:
            from backend.stock_domain.providers import AkShareMarketDataProvider
            self._delegate = AkShareMarketDataProvider()
        return self._delegate

    def search_news(self, symbol: str, query: str = "") -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            return MockIntelProvider().search_news(symbol, query)
        market = str(stock["market"])

        # For CN/HK, use AKShare's existing search_intel logic
        if market in ("CN", "HK"):
            try:
                return self._get_delegate().search_intel(normalized, query)
            except Exception:
                pass

        # Fallback for US or on error
        mock = MockIntelProvider()
        result = mock.search_news(normalized, query)
        result["degraded"] = True
        result["degraded_reason"] = f"{self.name} does not support {market} intel"
        return result


class IntelProviderRouter:
    """Routes news/intel search requests to the configured provider.

    Reads configuration from the repo (app_config key "intel_sources")
    to determine which provider to use for each intel category.
    """

    def __init__(self) -> None:
        self.repo: Any = None
        self._providers: dict[str, IntelProvider] = {
            "akshare": AkShareIntelProvider(),
            "mock": MockIntelProvider(),
        }

    def _provider_for_category(self, category: str) -> tuple[str, IntelProvider]:
        """Return (provider_id, provider) for the given intel category."""
        provider_id = "akshare"
        if self.repo is not None:
            try:
                from backend.config.intel_sources import DEFAULT_INTEL_SOURCES
                config = self.repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES)
                providers = config.get("providers", {})
                provider_id = providers.get(category, {}).get("provider", "akshare")
                if provider_id == "none":
                    provider_id = "mock"
            except Exception:
                provider_id = "akshare"
        provider = self._providers.get(provider_id, self._providers["mock"])
        return provider_id, provider

    def search_news(self, symbol: str, query: str = "") -> dict:
        _, provider = self._provider_for_category("news_search")
        started = time.perf_counter()
        try:
            return provider.search_news(symbol, query)
        except Exception as exc:
            fallback = self._providers["mock"]
            result = fallback.search_news(symbol, query)
            result["degraded"] = True
            result["degraded_reason"] = str(exc)
            return result

    def social_sentiment_summary(self, symbol: str) -> dict:
        """Return social sentiment data if configured, else empty."""
        provider_id, _ = self._provider_for_category("social_sentiment")
        if provider_id == "none":
            return {"enabled": False, "note": "社交舆情未启用"}
        return {"enabled": False, "provider": provider_id, "note": "功能预留"}


# Module singleton
intel_router = IntelProviderRouter()

from __future__ import annotations

from backend.stock_domain.intel_providers import intel_router
from backend.stock_domain.provider_router import provider_router


def search_stock_intel(symbol: str, query: str = "") -> dict:
    """Search stock intel/news using the configured intel source.

    Uses IntelRouter (configurable news_search provider) as primary.
    Falls back to the legacy provider_router for backward compatibility.
    """
    try:
        result = intel_router.search_news(symbol, query)
        if result.get("items") and len(result["items"]) > 0:
            return result
    except Exception:
        pass
    return provider_router.search_intel(symbol, query)


def social_sentiment(symbol: str) -> dict:
    """Return social sentiment data for a stock if configured."""
    return intel_router.social_sentiment_summary(symbol)

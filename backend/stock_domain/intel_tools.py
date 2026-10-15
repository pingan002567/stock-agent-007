from __future__ import annotations

from typing import Iterable

from backend.stock_domain.intel_providers import intel_router
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.result_projection import project_items, truncation_note
from backend.stock_domain.series_order import sort_intel_items

INTEL_FIELDS = ("type", "title", "source", "published_at", "updated_at", "url", "confidence")
INTEL_DEFAULT_LIMIT = 8

_MORE_HINT = "需要更多条目时调高 limit；需要正文/摘要等字段时用 fields 指定。"


def search_stock_intel(
    symbol: str,
    query: str = "",
    fields: Iterable[str] | None = None,
    limit: int | None = INTEL_DEFAULT_LIMIT,
) -> dict:
    """Search stock intel/news using the configured intel source.

    Uses IntelRouter (configurable news_search provider) as primary.
    Falls back to the legacy provider_router for backward compatibility.

    ``fields`` / ``limit`` 控制返回体量：情报条目常带长正文，整块塞进 agent
    线程会永久占用后续每一次模型调用的上下文。
    """
    result: dict | None = None
    try:
        candidate = intel_router.search_news(symbol, query)
        if candidate.get("items") and len(candidate["items"]) > 0:
            candidate["items"] = sort_intel_items(list(candidate["items"]))
            result = candidate
    except Exception:
        result = None
    if result is None:
        result = provider_router.search_intel(symbol, query)
        items = result.get("items")
        if isinstance(items, list):
            result["items"] = sort_intel_items(items)
    return _project_intel(result, fields, limit)


def _project_intel(
    raw: dict,
    fields: Iterable[str] | None,
    limit: int | None,
) -> dict:
    items = raw.get("items")
    if not isinstance(items, list):
        return raw
    # provider 可能返回缓存里的共享 dict，投影写进副本而不是原对象。
    result = {key: value for key, value in raw.items() if key != "items"}
    result["items"] = project_items(items, fields or INTEL_FIELDS, limit)
    note = truncation_note(
        returned=len(result["items"]),
        total=len(items),
        tool="search_stock_intel",
        hint=_MORE_HINT,
    )
    if note:
        result["truncated"] = note
    return result


def social_sentiment(symbol: str) -> dict:
    """Return social sentiment data for a stock if configured."""
    return intel_router.social_sentiment_summary(symbol)

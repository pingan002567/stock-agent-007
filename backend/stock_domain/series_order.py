"""个股时间序列统一排序：API 返回 newest-first（从上到下）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _parse_time(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.min
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw.replace(" ", "T")[:26])
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.combine(datetime.strptime(raw[:10], fmt).date(), datetime.min.time())
        except ValueError:
            continue
    return datetime.min


def sort_history_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(items, key=lambda item: _parse_time(item.get("date")), reverse=True)
    for idx, item in enumerate(ranked):
        item["day"] = idx + 1
    return ranked


def sort_intel_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: _parse_time(item.get("published_at") or item.get("updated_at")),
        reverse=True,
    )


def sort_financial_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _parse_time(item.get("report_date")), reverse=True)

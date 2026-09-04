from __future__ import annotations

from backend.stock_domain.series_order import (
    sort_financial_items,
    sort_history_items,
    sort_intel_items,
)


def test_sort_history_newest_first():
    items = [
        {"date": "2026-09-01", "close": 10},
        {"date": "2026-09-03", "close": 12},
        {"date": "2026-09-02", "close": 11},
    ]
    out = sort_history_items(items)
    assert [x["date"] for x in out] == ["2026-09-03", "2026-09-02", "2026-09-01"]
    assert [x["day"] for x in out] == [1, 2, 3]


def test_sort_intel_newest_first():
    items = [
        {"title": "old", "published_at": "2026-01-01"},
        {"title": "new", "published_at": "2026-09-03"},
    ]
    out = sort_intel_items(items)
    assert out[0]["title"] == "new"


def test_sort_financial_newest_first():
    items = [
        {"report_date": "2025-12-31"},
        {"report_date": "2026-06-30"},
    ]
    out = sort_financial_items(items)
    assert out[0]["report_date"] == "2026-06-30"

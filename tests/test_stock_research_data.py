from __future__ import annotations

import math

from backend.stock_domain.providers import _build_financial_items, _history_item


def test_build_financial_items_skips_nan_and_derives_balance_sheet():
    rows = [
        {
            "指标": "营业总收入",
            "20260630": 100.0,
            "20250930": float("nan"),
        },
        {
            "指标": "归母净利润",
            "20260630": 20.0,
            "20250930": 0.0,
        },
        {
            "指标": "股东权益合计(净资产)",
            "20260630": 80.0,
        },
        {
            "指标": "资产负债率",
            "20260630": 40.0,
        },
    ]
    items = _build_financial_items(rows)
    assert len(items) == 1
    assert items[0]["report_date"] == "2026-06-30"
    assert items[0]["revenue"] == 100.0
    assert items[0]["profit"] == 20.0
    assert math.isclose(items[0]["total_assets"], 133.33, rel_tol=1e-3)
    assert math.isclose(items[0]["total_liabilities"], 53.33, rel_tol=1e-3)


def test_history_item_derives_volume_from_amount_when_missing():
    item = _history_item(
        {
            "date": "2026-09-03",
            "open": 55.0,
            "high": 56.0,
            "low": 54.0,
            "close": 55.55,
            "amount": 202392499.0,
        },
        1,
        date_keys=("date",),
        open_keys=("open",),
        high_keys=("high",),
        low_keys=("low",),
        close_keys=("close",),
    )
    assert item["volume"] > 0
    assert math.isclose(item["volume"], 202392499.0 / 55.55, rel_tol=1e-3)

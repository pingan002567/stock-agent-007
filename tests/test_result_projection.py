from __future__ import annotations

import pytest

from backend.stock_domain import history_tools
from backend.stock_domain.history_tools import get_daily_history, summarize_history
from backend.stock_domain.intel_tools import search_stock_intel
from backend.stock_domain.result_projection import project_items, truncation_note

TOTAL_BARS = 30


@pytest.fixture()
def stub_history(monkeypatch):
    """Offline test providers return no bars; pin a deterministic 30-bar series.

    A single shared payload object is returned on every call, mirroring how
    provider_cache hands back the same dict — that is what makes in-place
    projection dangerous.
    """
    payload = {
        "symbol": "AAPL",
        "source": "test",
        "items": [
            {
                "date": f"2026-01-{TOTAL_BARS - i:02d}",
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000 + i,
            }
            for i in range(TOTAL_BARS)
        ],
    }
    monkeypatch.setattr(
        history_tools.provider_router, "get_history", lambda symbol, days: payload
    )
    return payload


def _bars() -> list[dict]:
    # newest-first, like sort_history_items produces
    return [
        {"day": 1, "date": "2026-01-05", "open": 11.0, "high": 12.0, "low": 10.5, "close": 11.5, "volume": 300},
        {"day": 2, "date": "2026-01-04", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.0, "volume": 200},
        {"day": 3, "date": "2026-01-03", "open": 9.0, "high": 10.0, "low": 8.0, "close": 9.0, "volume": 100},
    ]


def test_project_items_selects_fields_and_limit():
    rows = project_items(_bars(), ["date", "close"], 2)
    assert rows == [
        {"date": "2026-01-05", "close": 11.5},
        {"date": "2026-01-04", "close": 10.0},
    ]


def test_project_items_without_fields_copies_rows():
    original = _bars()
    rows = project_items(original)
    rows[0]["close"] = 999
    assert original[0]["close"] == 11.5


def test_truncation_note_is_omitted_when_nothing_was_dropped():
    assert truncation_note(returned=3, total=3, tool="t", hint="h") is None
    note = truncation_note(returned=1, total=3, tool="t", hint="h")
    assert note["returned"] == 1 and note["total"] == 3


def test_summarize_history_reports_range_and_risk_stats():
    summary = summarize_history(_bars())
    assert summary["bars"] == 3
    assert summary["period"] == {"start": "2026-01-03", "end": "2026-01-05"}
    assert summary["close"] == {"latest": 11.5, "first": 9.0}
    assert summary["change_pct"] == 27.78
    assert summary["high"] == 12.0
    assert summary["low"] == 8.0
    assert summary["avg_volume"] == 200.0
    assert summary["max_drawdown_pct"] == 0.0


def test_summarize_history_tolerates_missing_and_nan_values():
    summary = summarize_history([{"date": "", "close": None}, {"date": "", "close": float("nan")}])
    assert summary["bars"] == 2
    assert "close" not in summary


def test_get_daily_history_defaults_to_summary_with_sample_and_hint(stub_history):
    result = get_daily_history("AAPL", 30)

    assert result["detail"] == "summary"
    assert result["summary"]["bars"] == TOTAL_BARS
    assert len(result["items"]) == 5
    assert set(result["items"][0]) == {"date", "open", "high", "low", "close", "volume"}
    assert result["truncated"]["returned"] == 5
    assert result["truncated"]["total"] == TOTAL_BARS
    assert "detail='full'" in result["truncated"]["hint"]


def test_get_daily_history_full_keeps_every_bar_and_has_no_truncation_note(stub_history):
    result = get_daily_history("AAPL", 30, detail="full")

    assert len(result["items"]) == TOTAL_BARS
    assert "truncated" not in result
    assert "summary" not in result


def test_get_daily_history_ohlc_projects_requested_fields_only(stub_history):
    result = get_daily_history("AAPL", 30, detail="ohlc", fields=["date", "close"], limit=4)

    assert len(result["items"]) == 4
    assert set(result["items"][0]) == {"date", "close"}
    assert result["truncated"]["total"] == TOTAL_BARS


def test_get_daily_history_does_not_poison_the_provider_cache(stub_history):
    """Projection must not mutate the shared payload the provider cache hands back."""
    slim = get_daily_history("AAPL", 30)
    full = get_daily_history("AAPL", 30, detail="full")
    slim_again = get_daily_history("AAPL", 30)

    assert len(slim["items"]) == 5
    assert len(full["items"]) == TOTAL_BARS
    assert len(slim_again["items"]) == 5
    assert slim_again["summary"]["bars"] == TOTAL_BARS
    assert len(stub_history["items"]) == TOTAL_BARS


def test_get_daily_history_summary_is_much_smaller_than_full(stub_history):
    import json

    slim = len(json.dumps(get_daily_history("AAPL", 30), ensure_ascii=False))
    full = len(json.dumps(get_daily_history("AAPL", 30, detail="full"), ensure_ascii=False))
    assert slim < full / 3


def test_project_mapping_selects_fields():
    from backend.stock_domain.result_projection import project_mapping

    assert project_mapping({"a": 1, "b": 2, "c": 3}, ["a", "c"]) == {"a": 1, "c": 3}
    assert project_mapping({"a": 1}, None) == {"a": 1}


def test_search_stock_intel_limits_items_and_keeps_source():
    full = search_stock_intel("AAPL", limit=None)
    capped = search_stock_intel("AAPL", limit=1)

    assert "source" in capped
    assert len(capped["items"]) == 1
    if len(full["items"]) > 1:
        assert capped["truncated"]["total"] == len(full["items"])
    assert len(search_stock_intel("AAPL", limit=None)["items"]) == len(full["items"])


def test_search_stock_intel_projects_requested_fields():
    result = search_stock_intel("AAPL", fields=["title"], limit=2)
    assert all(set(item) == {"title"} for item in result["items"])

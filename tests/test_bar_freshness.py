from __future__ import annotations

from datetime import datetime

from backend.schemas import StockDaily
from backend.stock_domain.market_structure import _provisional_bar, _snapshot_block
from backend.stock_domain.provider_router import ProviderRouter, _annotate_history
from backend.stock_domain.providers import _session_from_mapping, _session_from_tencent
from backend.stock_domain.trading_calendar import expected_bar_date, session_bar_date


class _Repo:
    def __init__(self, trade_date: str) -> None:
        self.trade_date = trade_date

    def list_stock_daily(self, symbol: str, limit: int = 1):
        return [
            StockDaily(
                symbol=symbol,
                trade_date=self.trade_date,
                open=17.0,
                high=17.2,
                low=16.8,
                close=17.08,
                volume=1000,
                amount=17080,
            )
        ]

    def count_stock_daily(self, symbol: str) -> int:
        return 30


class _Primary:
    name = "akshare"

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def get_history(self, symbol: str, days: int = 30) -> dict:
        self.calls += 1
        return {
            "symbol": symbol,
            "source": self.name,
            "updated_at": "2026-09-14T08:00:00+00:00",
            "degraded": False,
            "degraded_reason": None,
            "items": [
                {
                    "date": "2026-09-14",
                    "open": 18.1,
                    "high": 18.9,
                    "low": 17.9,
                    "close": 18.79,
                    "volume": 2000,
                    "amount": 37000,
                }
            ],
        }


def test_expected_bar_date_rejects_weekend_gap_after_close():
    monday_close = datetime(2026, 9, 14, 16, 24)
    monday_open = datetime(2026, 9, 14, 10, 0)
    saturday = datetime(2026, 9, 12, 11, 0)

    assert expected_bar_date("CN", monday_close).isoformat() == "2026-09-14"
    assert expected_bar_date("CN", monday_open).isoformat() == "2026-09-11"
    assert expected_bar_date("CN", saturday).isoformat() == "2026-09-11"
    assert session_bar_date("CN", monday_open) is not None
    assert session_bar_date("CN", saturday) is None


def test_friday_cache_is_not_fresh_on_monday_after_close():
    primary = _Primary()
    router = ProviderRouter(primary=primary)
    router.repo = _Repo("2026-09-11")
    router._provider_for_market = lambda market: primary

    history = router.get_history("600519", days=1, now=datetime(2026, 9, 14, 16, 24))

    assert primary.calls == 1
    assert history["source"] != "cache"
    assert history["as_of"] == "2026-09-14"
    assert history["expected_as_of"] == "2026-09-14"
    assert history["stale"] is False


def test_friday_cache_is_fresh_on_saturday_and_does_not_stamp_now():
    primary = _Primary()
    router = ProviderRouter(primary=primary)
    router.repo = _Repo("2026-09-11")
    router._provider_for_market = lambda market: primary

    history = router.get_history("600519", days=1, now=datetime(2026, 9, 12, 11, 0))

    assert primary.calls == 0
    assert history["source"] == "cache"
    assert history["as_of"] == "2026-09-11"
    assert history["expected_as_of"] == "2026-09-11"
    assert history["stale"] is False
    assert history["updated_at"] == "2026-09-11"
    assert "T" not in history["updated_at"]


def test_cache_annotation_marks_stale_without_claiming_now():
    payload = _annotate_history(
        {
            "source": "cache",
            "updated_at": "2026-09-14T08:26:00+00:00",
            "items": [{"date": "2026-09-11", "close": 17.08}],
        },
        "CN",
        datetime(2026, 9, 14, 16, 24),
    )
    assert payload["stale"] is True
    assert payload["updated_at"] == "2026-09-11"
    assert payload["expected_as_of"] == "2026-09-14"


def test_session_fields_come_from_spot_row_and_tencent():
    session = _session_from_mapping(
        {"最新价": 18.79, "今开": 18.1, "最高": 18.9, "最低": 17.9, "成交量": 100, "换手率": "3.2%"},
        volume_unit="lot",
    )
    assert session["open"] == 18.1
    assert session["turnover_pct"] == 3.2
    assert session["volume_unit"] == "lot"

    fields = [""] * 50
    fields[3] = "18.79"
    fields[5] = "18.10"
    fields[33] = "18.90"
    fields[34] = "17.90"
    fields[6] = "1200"
    fields[39] = "22.5"
    fields[46] = "2.1"
    fields[45] = "10"
    parsed = _session_from_tencent(fields)
    assert parsed["open"] == 18.1
    assert parsed["pe"] == 22.5
    assert parsed["pb"] == 2.1
    assert parsed["total_market_cap"] == 1_000_000_000


def test_snapshot_keeps_quote_fields_when_individual_info_fails(monkeypatch):
    class Boom:
        def fetch_spot_snapshot(self, symbol):
            raise RuntimeError("RemoteDisconnected")

    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: Boom())
    snap = _snapshot_block(
        "CN",
        "002579",
        {
            "last": 18.79,
            "open": 18.1,
            "high": 18.9,
            "low": 17.9,
            "volume": 100,
            "pe": 22.0,
            "pb": 2.0,
            "total_market_cap": 1.0,
            "float_market_cap": 1.0,
            "turnover_pct": 3.0,
            "amplitude_pct": 5.0,
            "volume_ratio": 2.2,
        },
    )
    assert snap["pe"] == 22.0
    assert snap["open"] == 18.1
    assert snap["degraded"] is False
    assert snap["sources"]["pe"] == "session_quote"


def test_research_status_does_not_treat_score_zero_as_a_rating():
    from backend.app_services.context_builder import _research_status

    assert _research_status({"score": 0, "stance": ""}, False) == "未生成研报"
    assert _research_status({"score": 0, "stance": "观望"}, False) == "已有研报"
    assert _research_status({"score": 0, "stance": ""}, True) == "已有研报"


def test_provisional_bar_requires_ohlc_and_is_not_official():
    bar = _provisional_bar({"last": 18.79, "open": 18.1, "high": 18.9, "low": 17.9}, expected_bar_date("CN", datetime(2026, 9, 14, 16, 0)))
    assert bar is not None
    assert bar["provisional"] is True
    assert bar["close"] == 18.79
    assert "volume" not in bar
    assert _provisional_bar({"last": 18.79}, expected_bar_date("CN", datetime(2026, 9, 14, 16, 0))) is None

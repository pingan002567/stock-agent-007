from __future__ import annotations

import json
import math
import os
from datetime import date, timedelta

import pytest

from backend.stock_domain.market_structure import (
    compute_technical,
    get_market_structure,
    _chip_from_row,
    _json_safe,
)
from backend.stock_domain.report_tools import _generate_technical_analysis


def _bars(n: int = 20, start: float = 10.0, newest_first: bool = False) -> list[dict]:
    items = []
    origin = date(2026, 1, 1)
    for i in range(n):
        close = start + i
        items.append(
            {
                "date": (origin + timedelta(days=i)).isoformat(),
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000 + i,
            }
        )
    if newest_first:
        return list(reversed(items))
    return items


def test_compute_technical_ma_rsi_ascending_and_newest_first():
    bars = _bars(20, start=10.0)
    tech = compute_technical(bars)
    assert tech["degraded"] is False
    assert tech["ma5"] == 27.0
    assert tech["ma20"] == 19.5
    assert tech["ma60"] is None
    assert "ma60" in tech["missing"]
    assert tech["rsi14"] == 100.0
    assert tech["support_20"] == pytest.approx(9.5)
    assert tech["resistance_20"] == pytest.approx(29.5)

    reversed_tech = compute_technical(_bars(20, start=10.0, newest_first=True))
    assert reversed_tech["ma5"] == tech["ma5"]
    assert reversed_tech["rsi14"] == tech["rsi14"]
    assert reversed_tech["last"] == tech["last"]


def test_compute_technical_skips_nan_close_and_is_json_safe():
    bars = _bars(20)
    bars[3]["close"] = float("nan")
    tech = compute_technical(bars)
    json.dumps(tech, allow_nan=False)
    assert math.isnan(bars[3]["close"])
    assert tech["bar_count"] == 19


def test_chip_from_row_drops_nan_and_uses_market_avg_cost():
    bars = _bars(80)
    row = {
        "日期": "2026-09-03",
        "获利比例": float("nan"),
        "平均成本": 48.2,
        "90成本-低": 40.0,
        "90成本-高": 55.0,
    }
    chip = _chip_from_row(row, last=50.0, bars=bars)
    assert chip["degraded"] is False
    assert chip["profit_ratio"] is None
    assert chip["market_avg_cost"] == 48.2
    json.dumps(_json_safe(chip), allow_nan=False)


def test_hk_and_us_payload_have_no_chip_profit_keys(monkeypatch):
    history = {"items": _bars(40), "source": "akshare"}
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: history,
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._snapshot_block",
        lambda *a, **k: {"degraded": True, "reason": "test"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._flow_block",
        lambda *a, **k: {"degraded": True, "reason": "test"},
    )

    hk = get_market_structure("HK00700")
    assert hk["chip"]["degraded"] is True
    assert "profit_ratio" not in hk["chip"]
    assert "trapped_ratio" not in hk["chip"]
    assert hk["technical"]["ma5"] is not None
    json.dumps(hk, allow_nan=False)

    us = get_market_structure("AAPL")
    assert us["chip"]["degraded"] is True
    assert "profit_ratio" not in us["chip"]
    assert "trapped_ratio" not in us["chip"]
    json.dumps(us, allow_nan=False)


def test_provider_failure_does_not_use_mock_adapter(monkeypatch):
    class Boom:
        def fetch_chip_cyq(self, symbol):
            raise RuntimeError("cyq down")

        def fetch_fund_flow_rows(self, symbol, limit=12):
            raise RuntimeError("flow down")

        def fetch_spot_snapshot(self, symbol):
            raise RuntimeError("snap down")

    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: {"items": _bars(40), "source": "akshare"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._akshare_primary",
        lambda: Boom(),
    )
    payload = get_market_structure("600519")
    assert payload["source"] != "mock_adapter"
    assert payload["chip"]["degraded"] is True
    assert "profit_ratio" not in payload["chip"]
    assert payload["flow"]["degraded"] is True
    json.dumps(payload, allow_nan=False)


def test_technical_analysis_uses_real_support_not_percent_band():
    class Price:
        change_pct = 0.4
        last = 100.0

    class Context:
        symbol = "600519"
        price = Price()

    tech = _generate_technical_analysis(
        Context(),  # type: ignore[arg-type]
        {
            "technical": {
                "support_20": 91.5,
                "resistance_20": 108.2,
                "ma_stack": "bullish",
                "rsi14": 62,
                "ma5": 102.0,
                "ma20": 99.0,
            }
        },
    )
    assert tech["support"] == 91.5
    assert tech["resistance"] == 108.2
    assert tech["support"] != pytest.approx(95.0)


def test_tushare_rows_map_into_chip_and_flow():
    from backend.stock_domain.multi_providers import _cyq_perf_row, _moneyflow_row, _tushare_snapshot

    chip_row = _cyq_perf_row({
        "trade_date": "20260911",
        "winner_rate": 62.5,
        "weight_avg": 18.2,
        "cost_5pct": 16.1,
        "cost_95pct": 20.4,
        "cost_15pct": 17.0,
        "cost_85pct": 19.5,
    })
    chip = _chip_from_row(chip_row, last=18.8, bars=_bars(80))
    assert chip["degraded"] is False
    assert chip["method"] == "tushare_cyq_perf"
    assert chip["profit_ratio"] == pytest.approx(0.625)
    assert chip["market_avg_cost"] == 18.2
    assert chip["cost_90_low"] == 16.1
    assert chip["as_of"] == "2026-09-11"

    flow = _moneyflow_row({
        "trade_date": "20260911",
        "buy_elg_amount": 100.0,
        "sell_elg_amount": 40.0,
        "buy_lg_amount": 30.0,
        "sell_lg_amount": 10.0,
    })
    assert flow["日期"] == "2026-09-11"
    assert flow["超大单净流入-净额"] == 600000.0
    assert flow["主力净流入-净额"] == 800000.0

    snap = _tushare_snapshot(
        {"trade_date": "20260911", "pe_ttm": 22.5, "pb": 3.1, "total_mv": 100000.0, "circ_mv": 80000.0, "turnover_rate": 1.2, "volume_ratio": 0.9, "close": 18.8},
        {"high": 19.0, "low": 18.0, "pre_close": 18.5, "amount": 12.5},
    )
    assert snap["pe"] == 22.5
    assert snap["total_market_cap"] == 1_000_000_000.0
    assert snap["amount"] == 125000.0
    assert snap["amplitude_pct"] == pytest.approx(5.4054, rel=1e-3)


def test_cn_structure_uses_tushare_when_configured(monkeypatch):
    class Paid:
        name = "tushare"

        def is_available(self):
            return True

        def fetch_chip_cyq(self, symbol):
            return [{
                "日期": "2026-09-11",
                "获利比例": 50,
                "平均成本": 10,
                "method": "tushare_cyq_perf",
            }]

        def fetch_fund_flow_rows(self, symbol, limit=12):
            return [{"日期": "2026-09-11", "主力净流入-净额": 1000, "source": "tushare.moneyflow"}]

        def fetch_spot_snapshot(self, symbol):
            raise AssertionError("chip/flow test should not need snapshot")

    monkeypatch.setattr("backend.stock_domain.market_structure._tushare_structure_provider", lambda: Paid())
    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: None)
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: {"items": _bars(80), "source": "tushare"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._snapshot_block",
        lambda *a, **k: {"degraded": False, "pe": 12},
    )

    payload = get_market_structure("600519")
    assert payload["chip"]["method"] == "tushare_cyq_perf"
    assert payload["chip"]["degraded"] is False
    assert payload["flow"]["source"] == "tushare.moneyflow"
    assert payload["flow"]["main_net_1d"] == 1000


def test_tushare_refusal_falls_back_to_akshare(monkeypatch):
    class Paid:
        name = "tushare"

        def is_available(self):
            return True

        def fetch_fund_flow_rows(self, symbol, limit=12):
            raise RuntimeError("抱歉，您没有接口访问权限")

    class Free:
        name = "akshare"

        def fetch_fund_flow_rows(self, symbol, limit=12):
            return [{"日期": "2026-09-11", "主力净流入-净额": 20}]

    monkeypatch.setattr("backend.stock_domain.market_structure._tushare_structure_provider", lambda: Paid())
    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: Free())

    from backend.stock_domain.market_structure import _flow_block

    flow = _flow_block("CN", "600519")
    assert flow["degraded"] is False
    assert flow["source"] == "akshare"
    assert flow["main_net_1d"] == 20


def test_live_a_share_and_overseas_samples():
    if os.environ.get("MARKET_STRUCTURE_LIVE") != "1":
        pytest.skip("set MARKET_STRUCTURE_LIVE=1 to run live Eastmoney/yfinance checks")

    def _fetch(symbol: str) -> dict:
        try:
            return get_market_structure(symbol)
        except Exception as exc:
            pytest.skip(f"live market structure failed for {symbol}: {exc}")

    moutai = _fetch("600519")
    json.dumps(moutai, allow_nan=False)
    assert moutai["source"] != "mock_adapter"
    assert moutai["technical"].get("bar_count", 0) > 0
    if not moutai["chip"].get("degraded"):
        assert moutai["chip"].get("profit_ratio") is not None or moutai["chip"].get("market_avg_cost") is not None
    else:
        assert "profit_ratio" not in moutai["chip"]

    cxmt = _fetch("688825")
    json.dumps(cxmt, allow_nan=False)
    assert cxmt.get("symbol") == "688825"
    assert cxmt["source"] != "mock_adapter"

    aapl = _fetch("AAPL")
    json.dumps(aapl, allow_nan=False)
    assert "profit_ratio" not in aapl["chip"]
    assert "trapped_ratio" not in aapl["chip"]
    assert aapl["chip"].get("degraded") is True
    assert aapl["technical"].get("degraded") is False or aapl["technical"].get("bar_count", 0) >= 5

    hk = _fetch("HK00700")
    json.dumps(hk, allow_nan=False)
    assert "profit_ratio" not in hk["chip"]
    assert hk["chip"].get("degraded") is True
    assert hk["technical"].get("ma5") is not None or hk["technical"].get("bar_count", 0) >= 5


def test_cn_extra_blocks_from_tushare(monkeypatch):
    class Paid:
        name = "tushare"

        def is_available(self):
            return True

        def fetch_chip_cyq(self, symbol):
            return [{
                "日期": "2026-09-11",
                "获利比例": 50,
                "平均成本": 10,
                "method": "tushare_cyq_perf",
            }]

        def fetch_fund_flow_rows(self, symbol, limit=12):
            return [{"日期": "2026-09-11", "主力净流入-净额": 1000, "source": "tushare.moneyflow"}]

        def fetch_spot_snapshot(self, symbol):
            return {"pe": 12, "source": "tushare.daily_basic"}

        def fetch_northbound_hold(self, symbol):
            return {
                "degraded": False,
                "on_list": True,
                "as_of": "2024-08-19",
                "vol": 1e8,
                "ratio": 3.2,
                "exchange": "SH",
                "source": "tushare.hk_hold",
                "note": "test",
            }

        def fetch_margin_detail(self, symbol):
            return {
                "degraded": False,
                "available": True,
                "as_of": "2026-09-11",
                "rzye": 1e9,
                "rqye": 1e7,
                "rzmre": 1e8,
                "rzrqye": 1.01e9,
                "source": "tushare.margin_detail",
            }

        def fetch_lhb(self, symbol, lookback_days=20, limit=5):
            return {
                "degraded": False,
                "on_list": True,
                "as_of": "2026-09-10",
                "items": [{
                    "trade_date": "2026-09-10",
                    "reason": "日涨幅偏离值达到7%的前五只证券",
                    "net_amount": 1e7,
                    "l_buy": 2e7,
                    "l_sell": 1e7,
                }],
                "count": 1,
                "source": "tushare.top_list",
            }

        def fetch_share_float(self, symbol, limit=10):
            return {
                "degraded": False,
                "upcoming": [{
                    "float_date": "2026-12-01",
                    "float_share": 1e6,
                    "float_ratio": 0.5,
                    "holder_name": "某某",
                    "share_type": "定增股份",
                }],
                "recent": [],
                "upcoming_count": 1,
                "recent_count": 0,
                "source": "tushare.share_float",
            }

    monkeypatch.setattr("backend.stock_domain.market_structure._tushare_structure_provider", lambda: Paid())
    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: None)
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: {"items": _bars(80), "source": "tushare"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._snapshot_block",
        lambda *a, **k: {"degraded": False, "pe": 12},
    )

    payload = get_market_structure("600519")
    extra = payload["extra"]
    assert extra.get("coverage") != "not_wired"
    assert extra["applicable"] is True
    assert extra["missing"] == []
    assert extra["northbound"]["vol"] == 1e8
    assert extra["margin"]["rzye"] == 1e9
    assert extra["lhb"]["on_list"] is True
    assert extra["unlock"]["upcoming"][0]["float_date"] == "2026-12-01"


def test_cn_extra_partial_permission_failure(monkeypatch):
    class Paid:
        name = "tushare"

        def is_available(self):
            return True

        def fetch_chip_cyq(self, symbol):
            return [{"日期": "2026-09-11", "获利比例": 40, "平均成本": 11, "method": "tushare_cyq_perf"}]

        def fetch_fund_flow_rows(self, symbol, limit=12):
            return [{"日期": "2026-09-11", "主力净流入-净额": 100}]

        def fetch_northbound_hold(self, symbol):
            raise RuntimeError("抱歉，您没有接口访问权限")

        def fetch_margin_detail(self, symbol):
            return {
                "degraded": False,
                "available": True,
                "as_of": "2026-09-11",
                "rzye": 2e9,
                "source": "tushare.margin_detail",
            }

        def fetch_lhb(self, symbol, lookback_days=20, limit=5):
            return {"degraded": False, "on_list": False, "items": [], "count": 0, "source": "tushare.top_list"}

        def fetch_share_float(self, symbol, limit=10):
            return {"degraded": False, "upcoming": [], "recent": [], "upcoming_count": 0, "recent_count": 0, "source": "tushare.share_float"}

    monkeypatch.setattr("backend.stock_domain.market_structure._tushare_structure_provider", lambda: Paid())
    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: None)
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: {"items": _bars(80), "source": "tushare"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._snapshot_block",
        lambda *a, **k: {"degraded": False, "pe": 12},
    )

    payload = get_market_structure("600519")
    extra = payload["extra"]
    assert "northbound" in extra["missing"]
    assert extra["northbound"]["degraded"] is True
    assert extra["margin"]["degraded"] is False
    assert extra["margin"]["rzye"] == 2e9
    assert extra["lhb"]["on_list"] is False
    assert "not_wired" not in str(extra.get("coverage"))


def test_hk_extra_not_applicable(monkeypatch):
    monkeypatch.setattr("backend.stock_domain.market_structure._tushare_structure_provider", lambda: None)
    monkeypatch.setattr("backend.stock_domain.market_structure._akshare_primary", lambda: None)
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_daily_history",
        lambda *a, **k: {"items": _bars(20), "source": "akshare"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure._snapshot_block",
        lambda *a, **k: {"degraded": True, "reason": "test"},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.get_stock",
        lambda symbol: {"symbol": symbol, "name": "Tencent", "market": "HK", "price": 300},
    )
    monkeypatch.setattr(
        "backend.stock_domain.market_structure.normalize_symbol",
        lambda symbol: symbol if symbol.startswith("HK") else f"HK{symbol}",
    )

    payload = get_market_structure("HK00700")
    extra = payload["extra"]
    assert extra["applicable"] is False
    assert set(extra["missing"]) == {"northbound", "margin", "lhb", "unlock"}
    assert "A 股" in (extra["reason"] or "")
    assert extra["northbound"].get("degraded") is True

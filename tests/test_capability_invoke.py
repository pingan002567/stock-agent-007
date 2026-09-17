"""Mode A data-source catalog / invoke — no secrets in agent payloads."""

from __future__ import annotations

from backend.stock_domain.capability_invoke import (
    _scrub_secrets,
    describe_data_capability,
    invoke_data_capability,
    list_data_sources,
)
from backend.stock_domain.capability_registry import CAPABILITIES, capabilities_for_provider


def test_scrub_secrets_redacts_credential_keys():
    payload = {
        "token": "secret-token",
        "nested": {"api_key": "k", "ok": 1},
        "items": [{"app_secret": "x", "name": "a"}],
    }
    cleaned = _scrub_secrets(payload)
    assert cleaned["token"] == "***"
    assert cleaned["nested"]["api_key"] == "***"
    assert cleaned["nested"]["ok"] == 1
    assert cleaned["items"][0]["app_secret"] == "***"
    assert cleaned["items"][0]["name"] == "a"


def test_list_data_sources_has_no_secret_values(monkeypatch):
    catalog = list_data_sources()
    blob = str(catalog)
    assert "mode" in catalog
    assert catalog["providers"]
    assert "quote" in catalog["capabilities"]
    # credential field metadata may name env vars, but must not embed values
    for p in catalog["providers"]:
        assert "token_value" not in p
        for field in p.get("credential_fields") or []:
            assert "value" not in field
            assert field.get("configured") in (True, False)
    assert "sk-" not in blob.lower()


def test_describe_and_registry_cover_industry_caps():
    desc = describe_data_capability(capability="industry_boards")
    assert desc["ok"] is True
    assert "tonghuashun" in desc["providers"]
    assert "quote" in capabilities_for_provider("eastmoney")
    assert set(CAPABILITIES) >= {
        "quote",
        "history",
        "industry_boards",
        "industry_constituents",
        "cyq",
        "moneyflow",
    }


def test_invoke_rejects_unknown_capability():
    out = invoke_data_capability("eastmoney", "not_a_real_cap", {})
    assert out["ok"] is False
    assert "unknown capability" in out["error"]


def test_invoke_rejects_provider_capability_mismatch():
    out = invoke_data_capability("yfinance", "industry_boards", {})
    assert out["ok"] is False
    assert "does not offer" in out["error"]


def test_invoke_tonghuashun_industry_boards(monkeypatch):
    from backend.stock_domain import capability_invoke as ci

    monkeypatch.setattr(ci, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(ci, "is_provider_usable", lambda config, pid: True)

    fake_boards = [
        {"industry": "白酒", "change_pct": 1.2, "source": "ths"},
        {"industry": "半导体", "change_pct": -0.5, "source": "ths"},
    ]
    monkeypatch.setattr(
        "backend.stock_domain.industry_tools._boards_from_ths",
        lambda: fake_boards,
    )
    out = invoke_data_capability("tonghuashun", "industry_boards", {})
    assert out["ok"] is True
    assert out["provider"] == "tonghuashun"
    assert out["data"]["count"] == 2
    assert out["data"]["items"][0]["industry"] == "白酒"


def test_registry_includes_tushare_structure_caps():
    assert set(CAPABILITIES) >= {
        "northbound_hold",
        "margin_detail",
        "lhb",
        "share_float",
    }
    for name in ("northbound_hold", "margin_detail", "lhb", "share_float"):
        desc = describe_data_capability(capability=name)
        assert desc["ok"] is True
        assert desc["providers"] == ["tushare"]
    caps = capabilities_for_provider("tushare")
    assert "northbound_hold" in caps
    assert "share_float" in caps


def test_invoke_rejects_disabled_provider(monkeypatch):
    from backend.stock_domain import capability_invoke as ci

    monkeypatch.setattr(ci, "is_provider_usable", lambda config, pid: False)
    out = invoke_data_capability("tushare", "northbound_hold", {"symbol": "600519"})
    assert out["ok"] is False
    assert "not usable" in out["error"]
    assert "设置页" in (out.get("hint") or "")


def test_shared_gate_disabled_tushare_blocks_mode_a_and_policy(monkeypatch):
    """Same data_sources disable state → Mode A reject + Mode B policy unusable."""
    from backend.config.provider_policy import is_provider_usable
    from backend.stock_domain import capability_invoke as ci

    disabled = {
        "providers": {},
        "provider_states": {"tushare": {"enabled": False}},
        "credentials": {},
    }
    monkeypatch.setattr(ci, "_data_sources_config", lambda: disabled)
    monkeypatch.setattr(ci, "_throttle", lambda *a, **k: None)

    assert is_provider_usable(disabled, "tushare") is False
    out = invoke_data_capability("tushare", "margin_detail", {"symbol": "600519"})
    assert out["ok"] is False
    assert "not usable" in out["error"]


def test_invoke_tushare_structure_caps(monkeypatch):
    from backend.stock_domain import capability_invoke as ci

    monkeypatch.setattr(ci, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(ci, "is_provider_usable", lambda config, pid: True)

    class FakeTs:
        def fetch_northbound_hold(self, symbol):
            return {
                "degraded": False,
                "on_list": True,
                "as_of": "2024-08-19",
                "vol": 1e8,
                "ratio": 2.5,
                "source": "tushare.hk_hold",
                "token": "should-scrub",
            }

        def fetch_margin_detail(self, symbol):
            return {"degraded": False, "available": True, "rzye": 1e9, "as_of": "2026-09-11"}

        def fetch_lhb(self, symbol, lookback_days=20, limit=5):
            return {"degraded": False, "on_list": False, "items": [], "count": 0}

        def fetch_share_float(self, symbol, limit=10):
            return {
                "degraded": False,
                "upcoming": [{"float_date": "2026-12-01", "float_share": 1e6}],
                "recent": [],
                "upcoming_count": 1,
                "recent_count": 0,
            }

    monkeypatch.setattr(ci, "create_provider", lambda pid: FakeTs())

    nb = invoke_data_capability("tushare", "northbound_hold", {"symbol": "600519"})
    assert nb["ok"] is True
    assert nb["channel"] == "mode_a"
    assert nb["data"]["vol"] == 1e8
    assert nb["data"]["token"] == "***"

    mg = invoke_data_capability("tushare", "margin_detail", {"symbol": "600519"})
    assert mg["ok"] is True
    assert mg["data"]["rzye"] == 1e9

    lhb = invoke_data_capability("tushare", "lhb", {"symbol": "600519"})
    assert lhb["ok"] is True
    assert lhb["data"]["on_list"] is False

    sf = invoke_data_capability("tushare", "share_float", {"symbol": "600519"})
    assert sf["ok"] is True
    assert sf["data"]["upcoming"][0]["float_date"] == "2026-12-01"
    assert "token" not in str(sf).lower() or "***" in str(sf)


def test_quote_writeback_uses_router_ingest(monkeypatch):
    from backend.schemas import PriceSnapshot, now_iso
    from backend.stock_domain import capability_invoke as ci

    monkeypatch.setattr(ci, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(ci, "is_provider_usable", lambda config, pid: True)

    snap = PriceSnapshot(
        last=100.0,
        change_pct=1.0,
        updated_at=now_iso(),
        source="eastmoney",
        degraded=False,
    )

    class FakeQuote:
        def get_quote(self, symbol):
            return snap

    ingested: list[tuple] = []

    def _ingest(symbol, snapshot, *, provider_name=""):
        ingested.append((symbol, snapshot, provider_name))

    monkeypatch.setattr(ci, "create_provider", lambda pid: FakeQuote())
    monkeypatch.setattr(ci.provider_router, "ingest_quote", _ingest)

    out = invoke_data_capability("eastmoney", "quote", {"symbol": "600519"}, write_cache=True)
    assert out["ok"] is True
    assert len(ingested) == 1
    assert ingested[0][0] == "600519"
    assert ingested[0][1] is snap
    assert ingested[0][2] == "eastmoney"

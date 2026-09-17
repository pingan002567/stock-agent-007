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

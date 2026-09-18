"""Investor profile config + settings API."""

from __future__ import annotations

import pytest

from backend.config.investor_profile import (
    DEFAULT_INVESTOR_PROFILE,
    InvestorProfileError,
    format_profile_for_prompt,
    normalize_investor_profile,
)


def test_normalize_investor_profile_defaults_and_labels():
    assert normalize_investor_profile(None) == DEFAULT_INVESTOR_PROFILE
    assert normalize_investor_profile({})["risk_level"] == "moderate"
    aggressive = normalize_investor_profile({"risk_level": "aggressive", "notes": "  追主题  "})
    assert aggressive == {"risk_level": "aggressive", "notes": "追主题"}
    text = format_profile_for_prompt(aggressive)
    assert "激进" in text and "追主题" in text


def test_normalize_investor_profile_rejects_bad_level():
    with pytest.raises(InvestorProfileError):
        normalize_investor_profile({"risk_level": "yolo"})


def test_investor_profile_settings_roundtrip(tmp_path):
    from tests.test_api import make_client

    client = make_client(tmp_path)
    settings = client.get("/api/settings").json()
    assert settings["investor_profile"]["risk_level"] == "moderate"
    assert settings["investor_profile"]["notes"] == ""

    saved = client.put(
        "/api/settings/investor-profile",
        json={"risk_level": "conservative", "notes": "不追连板"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"risk_level": "conservative", "notes": "不追连板"}

    again = client.get("/api/settings").json()["investor_profile"]
    assert again["risk_level"] == "conservative"
    assert again["notes"] == "不追连板"

    bad = client.put("/api/settings/investor-profile", json={"risk_level": "yolo"})
    assert bad.status_code == 400

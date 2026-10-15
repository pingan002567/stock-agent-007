from backend.config.market_refresh import normalize_market_refresh


def test_market_refresh_clamps_and_fills_defaults():
    cleaned = normalize_market_refresh({"page_refresh_seconds": 5, "warmup_seconds": "900", "manual_cooldown_seconds": 99999})
    assert cleaned == {
        "page_refresh_seconds": 30,
        "warmup_seconds": 900,
        "manual_cooldown_seconds": 1800,
    }


def test_market_refresh_ignores_garbage():
    cleaned = normalize_market_refresh({"page_refresh_seconds": "soon"})
    assert cleaned["page_refresh_seconds"] == 60
    assert cleaned["warmup_seconds"] == 300
    assert cleaned["manual_cooldown_seconds"] == 120

"""User-facing market refresh intervals stored in the settings config table."""

from __future__ import annotations

from typing import Any

CONFIG_KEY = "market_refresh"

DEFAULT_MARKET_REFRESH: dict[str, int] = {
    "page_refresh_seconds": 60,
    "warmup_seconds": 300,
    "manual_cooldown_seconds": 120,
}

_BOUNDS: dict[str, tuple[int, int]] = {
    "page_refresh_seconds": (30, 600),
    "warmup_seconds": (120, 3600),
    "manual_cooldown_seconds": (30, 1800),
}


def normalize_market_refresh(raw: Any) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    out: dict[str, int] = {}
    for key, default in DEFAULT_MARKET_REFRESH.items():
        low, high = _BOUNDS[key]
        try:
            value = int(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        out[key] = min(high, max(low, value))
    return out


def load_market_refresh(repo: Any) -> dict[str, int]:
    if repo is None:
        return dict(DEFAULT_MARKET_REFRESH)
    try:
        stored = repo.get_config(CONFIG_KEY, DEFAULT_MARKET_REFRESH)
    except Exception:
        stored = DEFAULT_MARKET_REFRESH
    return normalize_market_refresh(stored)

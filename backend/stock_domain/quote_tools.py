from __future__ import annotations

import time
from typing import Any

from backend.schemas import PriceSnapshot, model_to_dict
from backend.stock_domain.catalog import normalize_symbol
from backend.stock_domain.provider_router import provider_router

_REFRESH_COOLDOWN_SECONDS = 120.0
_refresh_guard: dict[str, tuple[float, dict[str, Any]]] = {}


def _cooldown_seconds() -> float:
    repo = getattr(provider_router, "repo", None)
    if repo is None:
        return _REFRESH_COOLDOWN_SECONDS
    from backend.config.market_refresh import load_market_refresh

    return float(load_market_refresh(repo)["manual_cooldown_seconds"])


def get_realtime_quote(symbol: str) -> PriceSnapshot:
    return provider_router.get_quote(symbol)


def get_quote_card(symbol: str) -> dict:
    return {"symbol": normalize_symbol(symbol), "price": model_to_dict(get_realtime_quote(symbol))}


def refresh_market_data(symbol: str) -> dict[str, Any]:
    """Bypass quote/history caches once, then return freshness. Same symbol is not re-fetched for 120s."""
    normalized = normalize_symbol(symbol)
    now = time.time()
    hit = _refresh_guard.get(normalized)
    if hit is not None and now - hit[0] < _cooldown_seconds():
        payload = dict(hit[1])
        payload["skipped"] = True
        payload["reason"] = "同一标的本轮已刷新，未再次打穿缓存"
        return payload

    provider_router.invalidate_symbol_market(normalized)
    quote = provider_router.get_quote(normalized, force=True)
    history = provider_router.get_history(normalized, 90, force=True)
    from backend.stock_domain.market_structure import get_market_structure

    structure = get_market_structure(normalized)
    snapshot = structure.get("snapshot") if isinstance(structure.get("snapshot"), dict) else {}
    chip = structure.get("chip") if isinstance(structure.get("chip"), dict) else {}
    flow = structure.get("flow") if isinstance(structure.get("flow"), dict) else {}
    technical = structure.get("technical") if isinstance(structure.get("technical"), dict) else {}
    payload = {
        "symbol": normalized,
        "skipped": False,
        "quote": model_to_dict(quote),
        "history": {
            "as_of": history.get("as_of") if isinstance(history, dict) else None,
            "expected_as_of": history.get("expected_as_of") if isinstance(history, dict) else None,
            "stale": history.get("stale") if isinstance(history, dict) else None,
            "degraded": history.get("degraded") if isinstance(history, dict) else None,
            "degraded_reason": history.get("degraded_reason") if isinstance(history, dict) else None,
            "source": history.get("source") if isinstance(history, dict) else None,
        },
        "freshness": structure.get("freshness"),
        "snapshot_degraded": snapshot.get("degraded"),
        "snapshot_reason": snapshot.get("reason"),
        "chip_degraded": chip.get("degraded"),
        "chip_reason": chip.get("reason"),
        "flow_degraded": flow.get("degraded"),
        "flow_reason": flow.get("reason"),
        "technical_as_of": technical.get("as_of"),
        "technical_stale": technical.get("stale"),
        "technical_provisional": technical.get("provisional"),
    }
    _refresh_guard[normalized] = (now, payload)
    return payload

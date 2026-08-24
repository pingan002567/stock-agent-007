# -*- coding: utf-8 -*-
"""数据源启用/凭证策略：仅允许已激活且可用的 provider。"""
from __future__ import annotations

from backend.config.data_sources import (
    AVAILABLE_PROVIDERS,
    DEFAULT_DATA_SOURCES,
    PROVIDER_CREDENTIAL_SCHEMA,
)
from backend.stock_domain.provider_credentials import resolve as resolve_credential


def provider_catalog() -> dict[str, dict]:
    return {p["id"]: p for p in AVAILABLE_PROVIDERS}


def is_free_provider(provider_id: str) -> bool:
    meta = provider_catalog().get(provider_id)
    return bool(meta and meta.get("free"))


def default_provider_states() -> dict[str, dict[str, bool]]:
    states: dict[str, dict[str, bool]] = {}
    for item in AVAILABLE_PROVIDERS:
        pid = str(item["id"])
        enabled_default = bool(item.get("enabled_by_default", item.get("free", False)))
        states[pid] = {"enabled": enabled_default}
    return states


def merge_provider_states(config: dict) -> dict[str, dict[str, bool]]:
    merged = default_provider_states()
    raw = config.get("provider_states") or {}
    if isinstance(raw, dict):
        for pid, state in raw.items():
            if pid not in merged or not isinstance(state, dict):
                continue
            merged[pid] = {
                "enabled": bool(state.get("enabled", merged[pid]["enabled"])),
            }
    return merged


def is_provider_enabled(config: dict, provider_id: str) -> bool:
    states = merge_provider_states(config)
    return bool(states.get(provider_id, {}).get("enabled"))


def provider_credentials_complete(config: dict, provider_id: str) -> bool:
    fields = PROVIDER_CREDENTIAL_SCHEMA.get(provider_id) or []
    if not fields:
        return True
    creds = (config.get("provider_credentials") or {}).get(provider_id) or {}
    for field in fields:
        key = str(field["key"])
        value = creds.get(key)
        if value:
            continue
        if resolve_credential(provider_id, key):
            continue
        return False
    return True


def is_provider_usable(config: dict, provider_id: str) -> bool:
    if provider_id in ("mock", "none"):
        return False
    if provider_id not in provider_catalog():
        return False
    if not is_provider_enabled(config, provider_id):
        return False
    if is_free_provider(provider_id):
        return True
    return provider_credentials_complete(config, provider_id)


def selectable_providers_for_market(config: dict, market: str) -> list[str]:
    catalog = provider_catalog()
    out: list[str] = []
    for item in AVAILABLE_PROVIDERS:
        pid = str(item["id"])
        markets = item.get("markets") or []
        if market not in markets:
            continue
        if is_provider_usable(config, pid):
            out.append(pid)
    if out:
        return out
    # 兜底：任意已注册且支持该市场的免费 provider（即使未显式启用）
    for item in AVAILABLE_PROVIDERS:
        pid = str(item["id"])
        if market in (item.get("markets") or []) and item.get("free"):
            return [pid]
    return ["akshare" if market != "US" else "yfinance"]


def resolve_market_provider(config: dict, market: str) -> str:
    providers = config.get("providers") or DEFAULT_DATA_SOURCES.get("providers") or {}
    configured = str((providers.get(market) or {}).get("provider") or "")
    selectable = selectable_providers_for_market(config, market)
    if configured and configured in selectable:
        return configured
    return selectable[0]

# -*- coding: utf-8 -*-
"""数据源配置清洗：移除 mock 选项、迁移历史 mock 配置、合并 provider_states。"""
from __future__ import annotations

from backend.config.data_sources import DEFAULT_DATA_SOURCES
from backend.config.intel_sources import DEFAULT_INTEL_SOURCES
from backend.config.provider_policy import (
    merge_provider_states,
    provider_catalog,
    resolve_market_provider,
)

_MARKET_DEFAULT_PROVIDER = {
    m: cfg.get("provider", "eastmoney" if m != "US" else "yfinance")
    for m, cfg in DEFAULT_DATA_SOURCES.get("providers", {}).items()
}


def _default_market_provider(market: str) -> str:
    return _MARKET_DEFAULT_PROVIDER.get(
        market, "eastmoney" if market != "US" else "yfinance"
    )


def sanitize_data_sources(config: dict) -> dict:
    out = dict(config or {})
    merged_states = merge_provider_states(out)
    out["provider_states"] = merged_states
    if "provider_credentials" not in out or not isinstance(out.get("provider_credentials"), dict):
        out["provider_credentials"] = {}

    default_providers = dict(DEFAULT_DATA_SOURCES.get("providers") or {})
    providers = dict(out.get("providers") or {})
    if not providers:
        providers = {k: dict(v) for k, v in default_providers.items()}
    changed = bool(not out.get("providers"))
    allowed = _allowed_market_provider_ids()
    for market, default_cfg in default_providers.items():
        cfg = providers.get(market)
        if not isinstance(cfg, dict):
            cfg = dict(default_cfg)
            providers[market] = cfg
            changed = True
        pid = str(cfg.get("provider") or "")
        resolved = resolve_market_provider({**out, "providers": providers}, market)
        if pid == "mock" or pid not in allowed or pid != resolved:
            cfg = {**cfg, "provider": resolved}
            providers[market] = cfg
            changed = True
    if changed or "providers" not in out:
        out["providers"] = providers
    return out


def _allowed_market_provider_ids() -> set[str]:
    return set(provider_catalog().keys())


def sanitize_intel_sources(config: dict) -> dict:
    out = dict(config or {})
    providers = dict(out.get("providers") or {})
    defaults = DEFAULT_INTEL_SOURCES.get("providers", {})
    changed = False
    for category, default_cfg in defaults.items():
        cfg = providers.get(category)
        if not isinstance(cfg, dict):
            providers[category] = dict(default_cfg)
            changed = True
            continue
        merged = {**default_cfg, **cfg}
        pid = str(merged.get("provider") or "")
        if pid == "mock":
            merged["provider"] = default_cfg.get("provider", "eastmoney")
            changed = True
        if "enabled" not in merged:
            merged["enabled"] = bool(default_cfg.get("enabled", True))
            changed = True
        providers[category] = merged
    if changed or "providers" not in out:
        out["providers"] = providers
    return out

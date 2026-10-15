"""Mode A invoke path: catalog / describe / invoke with server-side credentials.

Secrets stay in DB/env and never appear in tool results. Provider instances
already resolve credentials via ``provider_credentials.resolve``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.config.data_source_sanitize import sanitize_data_sources
from backend.config.data_sources import AVAILABLE_PROVIDERS, DEFAULT_DATA_SOURCES, PROVIDER_CREDENTIAL_SCHEMA
from backend.config.provider_policy import (
    is_provider_enabled,
    is_provider_usable,
    merge_provider_states,
    provider_credentials_complete,
)
from backend.schemas import PriceSnapshot, model_to_dict, now_iso
from backend.stock_domain.capability_registry import (
    CAPABILITIES,
    PROVIDER_AGENT_META,
    capabilities_for_provider,
    capability_to_dict,
    get_capability,
)
from backend.stock_domain.multi_providers import create_provider
from backend.stock_domain.provider_router import provider_router

_log = logging.getLogger("capability_invoke")

# Per-process min interval between invokes for the same (provider, capability).
_MIN_INTERVAL_S = {
    "eastmoney": 3.0,
    "akshare": 3.0,
    "tonghuashun": 1.5,
    "yfinance": 2.0,
    "tushare": 0.35,
}
_last_invoke_at: dict[tuple[str, str], float] = {}
_MAX_RESULT_ITEMS = 80


def _data_sources_config() -> dict:
    if provider_router.repo is not None:
        raw = provider_router.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
        return sanitize_data_sources(dict(raw or {}))
    return sanitize_data_sources(dict(DEFAULT_DATA_SOURCES))


def _scrub_secrets(obj: Any) -> Any:
    """Best-effort strip of credential-looking keys from nested results."""
    secret_keys = {
        "token", "api_key", "app_key", "app_secret", "password", "secret",
        "authorization", "access_token", "refresh_token",
    }
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in secret_keys:
                out[k] = "***"
            else:
                out[k] = _scrub_secrets(v)
        return out
    if isinstance(obj, list):
        return [_scrub_secrets(x) for x in obj[:_MAX_RESULT_ITEMS]]
    return obj


def _throttle(provider_id: str, capability: str) -> None:
    key = (provider_id, capability)
    min_gap = _MIN_INTERVAL_S.get(provider_id, 1.0)
    last = _last_invoke_at.get(key, 0.0)
    wait = min_gap - (time.time() - last)
    if wait > 0:
        time.sleep(min(wait, 5.0))
    _last_invoke_at[key] = time.time()


def list_data_sources() -> dict[str, Any]:
    """Agent-safe catalog: no credential values."""
    config = _data_sources_config()
    states = merge_provider_states(config)
    market_primary = {
        market: (cfg or {}).get("provider")
        for market, cfg in (config.get("providers") or {}).items()
    }
    providers_out: list[dict[str, Any]] = []
    for item in AVAILABLE_PROVIDERS:
        pid = str(item["id"])
        meta = PROVIDER_AGENT_META.get(pid) or {}
        schema = PROVIDER_CREDENTIAL_SCHEMA.get(pid) or []
        caps = capabilities_for_provider(pid)
        enabled = is_provider_enabled(config, pid)
        usable = is_provider_usable(config, pid)
        creds_ok = provider_credentials_complete(config, pid) if schema else True
        # Probe availability without leaking errors that contain tokens.
        available = False
        try:
            provider = create_provider(pid)
            available = bool(provider.is_available())
        except Exception:
            available = False
        providers_out.append({
            "id": pid,
            "name": item.get("name"),
            "markets": list(item.get("markets") or []),
            "free": bool(item.get("free")),
            "description": item.get("description"),
            "auth_method": meta.get("auth_method") or ("none_public" if item.get("free") else "unknown"),
            "auth_description": meta.get("auth_description") or item.get("requirements"),
            "rate_limit_hint": meta.get("rate_limit_hint") or "",
            "capabilities": caps,
            "enabled": enabled,
            "credentials_configured": creds_ok,
            "usable": usable,
            "runtime_available": available,
            "health": (
                "ok" if usable and available
                else "needs_credentials" if enabled and not creds_ok
                else "disabled" if not enabled
                else "unavailable"
            ),
            "credential_fields": [
                {
                    "key": f["key"],
                    "label": f.get("label"),
                    "hint": f.get("hint"),
                    "configured": bool(
                        ((config.get("provider_credentials") or {}).get(pid) or {}).get(f["key"])
                    ) or False,
                    # Never expose env values — only whether a non-empty env name is expected.
                    "env": f.get("env"),
                }
                for f in schema
            ],
        })
    return {
        "mode": "agent_autonomous",
        "updated_at": now_iso(),
        "market_primary_providers": market_primary,
        "provider_states": states,
        "providers": providers_out,
        "capabilities": sorted(CAPABILITIES),
        "usage": (
            "复杂/降级/跨源：先 list_data_sources → describe_data_capability → "
            "invoke_data_capability(provider, capability, params)。"
            "密钥由服务端注入，勿要求用户粘贴 Token。"
        ),
    }


def describe_data_capability(
    provider: str | None = None,
    capability: str | None = None,
) -> dict[str, Any]:
    if capability:
        spec = get_capability(capability)
        if spec is None:
            return {
                "ok": False,
                "error": f"unknown capability: {capability}",
                "available": sorted(CAPABILITIES),
            }
        payload = capability_to_dict(spec)
        if provider:
            if provider not in spec.providers:
                payload["ok"] = False
                payload["error"] = f"provider {provider!r} does not offer {capability}"
                payload["suggested_providers"] = list(spec.providers)
            else:
                payload["ok"] = True
                payload["selected_provider"] = provider
                meta = PROVIDER_AGENT_META.get(provider) or {}
                payload["provider_auth_method"] = meta.get("auth_method")
                payload["provider_auth_description"] = meta.get("auth_description")
        else:
            payload["ok"] = True
        return payload

    if provider:
        caps = capabilities_for_provider(provider)
        meta = PROVIDER_AGENT_META.get(provider) or {}
        return {
            "ok": True,
            "provider": provider,
            "auth_method": meta.get("auth_method"),
            "auth_description": meta.get("auth_description"),
            "rate_limit_hint": meta.get("rate_limit_hint"),
            "capabilities": [capability_to_dict(CAPABILITIES[c]) for c in caps if c in CAPABILITIES],
        }

    return {
        "ok": True,
        "capabilities": [capability_to_dict(s) for s in CAPABILITIES.values()],
    }


def _require_param(params: dict[str, Any], name: str) -> Any:
    if name not in params or params[name] in (None, ""):
        raise ValueError(f"missing required param: {name}")
    return params[name]


def _serialize_result(raw: Any) -> Any:
    if isinstance(raw, PriceSnapshot):
        return model_to_dict(raw)
    if hasattr(raw, "__dataclass_fields__"):
        try:
            return model_to_dict(raw)
        except Exception:
            pass
    return _scrub_secrets(raw)


def _invoke_industry_boards(provider_id: str) -> dict[str, Any]:
    from backend.stock_domain import industry_tools as it

    if provider_id == "tonghuashun":
        boards = it._boards_from_ths()
        source = "ths"
    else:
        provider = create_provider(provider_id)
        boards = []
        if hasattr(provider, "fetch_industry_boards"):
            boards = provider.fetch_industry_boards() or []
        if not boards and provider_id in {"eastmoney", "akshare"}:
            boards = it._boards_from_ths()
            source = "ths_fallback"
        else:
            source = provider_id
    return {
        "items": boards[:_MAX_RESULT_ITEMS],
        "count": len(boards),
        "source": source if boards else provider_id,
        "degraded": not bool(boards),
    }


def _invoke_industry_constituents(provider_id: str, industry: str) -> dict[str, Any]:
    from backend.stock_domain import industry_tools as it

    rows: list[dict[str, Any]] = []
    source = provider_id
    if provider_id != "tonghuashun":
        provider = create_provider(provider_id)
        if hasattr(provider, "fetch_industry_constituents"):
            rows = provider.fetch_industry_constituents(industry) or []
    if not rows:
        rows = it._constituents_from_master(industry)
        source = "stock_master+spot"
    return {
        "industry": industry,
        "items": rows[:_MAX_RESULT_ITEMS],
        "count": len(rows),
        "source": source,
        "degraded": not bool(rows),
    }


def _invoke_cyq(provider_id: str, symbol: str) -> dict[str, Any]:
    provider = create_provider(provider_id)
    if not hasattr(provider, "fetch_chip_cyq"):
        raise ValueError(f"{provider_id} does not support cyq")
    rows = provider.fetch_chip_cyq(symbol) or []
    return {"symbol": symbol, "items": rows[:_MAX_RESULT_ITEMS], "source": provider_id, "count": len(rows)}


def _invoke_moneyflow(provider_id: str, symbol: str) -> dict[str, Any]:
    provider = create_provider(provider_id)
    if hasattr(provider, "fetch_fund_flow_rows"):
        rows = provider.fetch_fund_flow_rows(symbol) or []
    elif hasattr(provider, "fetch_moneyflow"):
        rows = provider.fetch_moneyflow(symbol) or []
    elif hasattr(provider, "fetch_fund_flow"):
        rows = provider.fetch_fund_flow(symbol) or []
    else:
        raise ValueError(f"{provider_id} does not support moneyflow")
    return {"symbol": symbol, "items": rows[:_MAX_RESULT_ITEMS], "source": provider_id, "count": len(rows)}


def _invoke_tushare_structure(provider_id: str, method: str, symbol: str, **kwargs: Any) -> dict[str, Any]:
    if provider_id != "tushare":
        raise ValueError(f"{method} is only available via tushare")
    provider = create_provider(provider_id)
    fn = getattr(provider, method, None)
    if not callable(fn):
        raise ValueError(f"{provider_id} does not support {method}")
    raw = fn(symbol, **kwargs)
    if not isinstance(raw, dict):
        raise ValueError(f"{method} returned unexpected payload")
    out = dict(raw)
    out.setdefault("symbol", symbol)
    out.setdefault("source", f"tushare.{method}")
    return out


def invoke_data_capability(
    provider: str,
    capability: str,
    params: dict[str, Any] | None = None,
    *,
    write_cache: bool = True,
) -> dict[str, Any]:
    """Run a named capability on an explicit provider (Mode A)."""
    params = dict(params or {})
    provider_id = (provider or "").strip()
    cap = (capability or "").strip()
    spec = get_capability(cap)
    if not provider_id:
        return {"ok": False, "error": "provider is required"}
    if spec is None:
        return {"ok": False, "error": f"unknown capability: {cap}", "available": sorted(CAPABILITIES)}
    if provider_id not in spec.providers:
        return {
            "ok": False,
            "error": f"provider {provider_id!r} does not offer {cap}",
            "suggested_providers": list(spec.providers),
        }

    config = _data_sources_config()
    if not is_provider_usable(config, provider_id):
        return {
            "ok": False,
            "error": f"provider {provider_id!r} is not usable (disabled or missing credentials)",
            "hint": "在设置页启用数据源并填写凭证；密钥不会出现在本工具返回中。",
        }

    for p in spec.params:
        if p.required and (p.name not in params or params[p.name] in (None, "")):
            return {"ok": False, "error": f"missing required param: {p.name}", "params_schema": capability_to_dict(spec)["params"]}

    try:
        _throttle(provider_id, cap)
        raw: Any
        if cap == "quote":
            symbol = str(_require_param(params, "symbol"))
            raw = create_provider(provider_id).get_quote(symbol)
            if write_cache and isinstance(raw, PriceSnapshot):
                try:
                    provider_router.ingest_quote(
                        symbol, raw, provider_name=provider_id
                    )
                except Exception:
                    pass
        elif cap == "history":
            symbol = str(_require_param(params, "symbol"))
            days = int(params.get("days") or 30)
            raw = create_provider(provider_id).get_history(symbol, days=days)
        elif cap == "financial":
            symbol = str(_require_param(params, "symbol"))
            raw = create_provider(provider_id).get_financial(symbol)
        elif cap == "industry_boards":
            raw = _invoke_industry_boards(provider_id)
        elif cap == "industry_constituents":
            industry = str(_require_param(params, "industry"))
            raw = _invoke_industry_constituents(provider_id, industry)
        elif cap == "sectors":
            raw = create_provider(provider_id).get_sectors()
        elif cap == "market_review":
            raw = create_provider(provider_id).get_market_review()
        elif cap == "intel_search":
            symbol = str(_require_param(params, "symbol"))
            query = str(params.get("query") or "")
            raw = create_provider(provider_id).search_intel(symbol, query=query)
        elif cap == "cyq":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_cyq(provider_id, symbol)
        elif cap == "moneyflow":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_moneyflow(provider_id, symbol)
        elif cap == "northbound_hold":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_tushare_structure(provider_id, "fetch_northbound_hold", symbol)
        elif cap == "margin_detail":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_tushare_structure(provider_id, "fetch_margin_detail", symbol)
        elif cap == "lhb":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_tushare_structure(
                provider_id, "fetch_lhb", symbol, lookback_days=20, limit=5
            )
        elif cap == "share_float":
            symbol = str(_require_param(params, "symbol"))
            raw = _invoke_tushare_structure(
                provider_id, "fetch_share_float", symbol, limit=10
            )
        else:
            return {"ok": False, "error": f"capability not implemented: {cap}"}

        data = _serialize_result(raw)
        return {
            "ok": True,
            "provider": provider_id,
            "capability": cap,
            "updated_at": now_iso(),
            "channel": "mode_a",
            "data": data,
        }
    except Exception as exc:
        _log.warning("invoke_data_capability(%s,%s) failed: %s", provider_id, cap, exc)
        msg = str(exc)
        # Avoid leaking tokens if a provider embeds them in errors.
        for secret_marker in ("token=", "api_key=", "app_secret="):
            if secret_marker in msg.lower():
                msg = "upstream error (details redacted)"
                break
        return {
            "ok": False,
            "provider": provider_id,
            "capability": cap,
            "error": msg,
            "hint": "可 list_data_sources 查看其它 usable 源后换 provider 重试；或 web_search 并标精度有限。",
        }

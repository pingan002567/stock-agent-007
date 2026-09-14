from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.config.models import DEFAULT_MODELS
from backend.config.profiles import DEFAULT_PROFILES
from backend.config.providers import DEFAULT_PROVIDERS
from backend.config.runtime import DEFAULT_RUNTIME_CONFIG
from backend.config.tools import DEFAULT_TOOLS
from backend.config.data_sources import AVAILABLE_PROVIDERS, DEFAULT_DATA_SOURCES, PROVIDER_CREDENTIAL_SCHEMA
from backend.config.market_refresh import CONFIG_KEY as MARKET_REFRESH_KEY
from backend.config.market_refresh import load_market_refresh, normalize_market_refresh
from backend.config.data_source_sanitize import sanitize_data_sources, sanitize_intel_sources
from backend.config.intel_sources import (
    AVAILABLE_INTEL_PROVIDERS,
    AVAILABLE_SENTIMENT_PROVIDERS,
    DEFAULT_INTEL_SOURCES,
)
from backend.agent_runtime import extensions_store
from backend.stock_domain.provider_router import provider_router
from backend.app_services.llm_provider_service import LlmProviderError
from backend.config.credentials import effective_runtime_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _public_runtime_config(repo) -> dict:
    """GET 回显用：合成 runtime，但去掉明文 api_key。"""
    cfg = dict(effective_runtime_config(repo) or {})
    has_key = bool(cfg.get("api_key"))
    cfg["api_key"] = None
    cfg["has_api_key"] = has_key
    return cfg



@router.get("")
def get_settings(request: Request, services: AppServices = Depends(get_services)):
    tools = (
        services.copilot_service.deerflow.tool_bridge.list_tools()
        if services.copilot_service.deerflow.tool_bridge
        else DEFAULT_TOOLS
    )
    return {
        "providers": services.repo.get_config(
            "providers", {"items": DEFAULT_PROVIDERS}
        )["items"],
        "models": services.repo.get_config("models", {"items": DEFAULT_MODELS})[
            "items"
        ],
        # 技能启停单一属主 = extensions_config.json（DeerFlow 直接消费）
        "skills": extensions_store.skills_view(),
        "profiles": services.repo.get_config("profiles", {"items": DEFAULT_PROFILES})[
            "items"
        ],
        "tools": tools,
        "risk_policy": services.risk_policy_service.settings_summary(),
        "trading_controls": {
            "paper_trading": "sandbox_only",
            "real_order": "blocked",
        },
        # 兼容两种配置格式：直接在顶层或在 config 子键下
        # 展示分层合成后的有效配置（用户级凭证 + 档案覆盖），密钥不回显
        "runtime_config": _public_runtime_config(services.repo),
        "agent_runtime": services.copilot_service.deerflow.status().to_dict(),
        "data_provider": provider_router.status().to_dict(),
        "market_refresh": load_market_refresh(services.repo),
        "data_sources": sanitize_data_sources(
            services.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
        ),
        "available_data_providers": AVAILABLE_PROVIDERS,
        "provider_credential_schema": PROVIDER_CREDENTIAL_SCHEMA,
        "intel_sources": sanitize_intel_sources(
            services.repo.get_config("intel_sources", DEFAULT_INTEL_SOURCES)
        ),
        "available_intel_providers": AVAILABLE_INTEL_PROVIDERS,
        "available_sentiment_providers": AVAILABLE_SENTIMENT_PROVIDERS,
        "llm_providers": services.llm_provider_service.snapshot(),
    }


@router.put("/providers")
def put_providers(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings providers updated", "providers")
    return services.repo.set_config("providers", payload)


@router.put("/models")
def put_models(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings models updated", "models")
    return services.repo.set_config("models", payload)


@router.put("/skills")
def put_skills(
    payload: dict, services: AppServices = Depends(get_services)
):
    """技能启停：写 extensions_config.json（单一属主）并重建 runtime。"""
    name = str(payload.get("name") or "")
    try:
        extensions_store.set_skill_enabled(name, bool(payload.get("enabled")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    services.audit_service.record(f"skill {name} -> {payload.get('enabled')}", "skills")
    status = services.copilot_service.reconnect_runtime()
    return {"skills": extensions_store.skills_view(), "agent_runtime": status}


@router.put("/profiles")
def put_profiles(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings profiles updated", "profiles")
    return services.repo.set_config("profiles", payload)


@router.put("/runtime")
def put_runtime(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings runtime updated", "runtime")
    # 凭证分层：api_key/base_url 跟人走（用户级 credentials.json），
    # 档案 DB 只存偏好（模型/思维链等）。base_url 与 key 配套故同归用户级。
    from backend.config.credentials import save_credentials

    cred_part = {k: payload.pop(k) for k in ("api_key", "base_url") if payload.get(k)}
    if cred_part:
        save_credentials(cred_part)
    result = services.repo.set_config("runtime", payload)
    # Auto-reconnect so the new config takes effect immediately
    status = services.copilot_service.reconnect_runtime()
    return {**result, "agent_runtime": status}


@router.put("/market-refresh")
def put_market_refresh(
    payload: dict, services: AppServices = Depends(get_services)
):
    cleaned = normalize_market_refresh(payload)
    services.audit_service.record("settings market refresh updated", MARKET_REFRESH_KEY)
    services.repo.set_config(MARKET_REFRESH_KEY, cleaned)
    return cleaned


@router.get("/llm/providers")
def llm_providers(services: AppServices = Depends(get_services)):
    return services.llm_provider_service.snapshot()


@router.post("/llm/connect")
def llm_connect(payload: dict, services: AppServices = Depends(get_services)):
    try:
        return services.llm_provider_service.connect(
            str(payload.get("provider_id") or ""),
            api_key=payload.get("api_key"),
        )
    except LlmProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/llm/providers/{provider_id}")
def llm_disconnect(provider_id: str, services: AppServices = Depends(get_services)):
    try:
        return services.llm_provider_service.disconnect(provider_id)
    except LlmProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/llm/custom")
def llm_upsert_custom(payload: dict, services: AppServices = Depends(get_services)):
    try:
        return services.llm_provider_service.upsert_custom(payload)
    except LlmProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/llm/default-model")
def llm_set_default_model(payload: dict, services: AppServices = Depends(get_services)):
    try:
        return services.llm_provider_service.set_default_model(str(payload.get("default_model") or ""))
    except LlmProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/llm/test")
def llm_test_connection(payload: dict, services: AppServices = Depends(get_services)):
    extra = services.llm_provider_service.test_payload(payload)
    spec = None
    provider_id = extra.get("provider_id")
    if provider_id:
        from backend.config.llm_catalog import get_provider_spec
        spec = get_provider_spec(str(provider_id))
    if spec is not None and not spec.requires_key:
        extra["allow_empty_key"] = True
    result = services.copilot_service.test_connection(extra)
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.put("/data-provider")
def put_data_provider(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings data provider updated", "data_sources")
    cleaned = sanitize_data_sources(payload)
    result = services.repo.set_config("data_sources", cleaned)
    # Clear provider cache so new config takes effect immediately
    provider_router.clear_cache()
    return result


@router.put("/intel-sources")
def put_intel_sources(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings intel sources updated", "intel_sources")
    return services.repo.set_config("intel_sources", sanitize_intel_sources(payload))


@router.put("/tools")
def put_tools(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record(
        "settings tools update rejected", "tool registry is runtime-owned"
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Workbench Tool Bridge registry is runtime-owned and cannot be overwritten from settings.",
    )


@router.get("/data-provider/health")
def data_provider_health(request: Request, services: AppServices = Depends(get_services)):
    """Check health status of all configured data providers."""
    config = services.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
    providers = config.get("providers", {})
    health_status = {}
    
    for market, provider_config in providers.items():
        provider_id = provider_config.get("provider", "akshare")
        if provider_id == "mock":
            provider_id = "yfinance" if market == "US" else "akshare"
        try:
            from backend.stock_domain.multi_providers import create_provider
            provider = create_provider(provider_id)
            is_available = provider.is_available()
            health_status[market] = {
                "provider": provider_id,
                "available": is_available,
                "status": "healthy" if is_available else "unavailable",
            }
        except Exception as e:
            health_status[market] = {
                "provider": provider_id,
                "available": False,
                "status": "error",
                "error": str(e),
            }
    
    return {
        "overall_status": "healthy" if all(h["available"] for h in health_status.values()) else "degraded",
        "providers": health_status,
    }


@router.patch("/data-provider/{market}")
def patch_data_provider(
    market: str,
    payload: dict,
    request: Request,
    services: AppServices = Depends(get_services),
):
    """Incrementally update a single market's data provider config."""
    config = services.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
    providers = config.get("providers", {})
    
    if market not in providers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Market '{market}' not found in data sources config",
        )
    
    # Merge updates
    providers[market].update(payload)
    config["providers"] = providers
    
    services.audit_service.record("settings data provider patched", f"market={market}")
    result = services.repo.set_config("data_sources", config)
    provider_router.clear_cache(market)
    return result


@router.delete("/data-provider/{market}")
def delete_data_provider(
    market: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    """Remove a market's data provider config (reverts to default)."""
    config = services.repo.get_config("data_sources", DEFAULT_DATA_SOURCES)
    providers = config.get("providers", {})
    
    if market not in providers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Market '{market}' not found in data sources config",
        )
    
    # Restore default for this market
    default_providers = DEFAULT_DATA_SOURCES.get("providers", {})
    if market in default_providers:
        providers[market] = default_providers[market]
    else:
        del providers[market]
    
    config["providers"] = providers
    
    services.audit_service.record("settings data provider deleted", f"market={market}")
    result = services.repo.set_config("data_sources", config)
    provider_router.clear_cache(market)
    return result

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.config.models import DEFAULT_MODELS
from backend.config.profiles import DEFAULT_PROFILES
from backend.config.providers import DEFAULT_PROVIDERS
from backend.config.runtime import DEFAULT_RUNTIME_CONFIG
from backend.config.skills import DEFAULT_SKILL_CONFIG
from backend.config.tools import DEFAULT_TOOLS
from backend.config.data_sources import AVAILABLE_PROVIDERS, DEFAULT_DATA_SOURCES
from backend.config.intel_sources import (
    AVAILABLE_INTEL_PROVIDERS,
    AVAILABLE_SENTIMENT_PROVIDERS,
    DEFAULT_INTEL_SOURCES,
)
from backend.stock_domain.provider_router import provider_router

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
        "skills": services.repo.get_config("skills", {"items": DEFAULT_SKILL_CONFIG})[
            "items"
        ],
        "profiles": services.repo.get_config("profiles", {"items": DEFAULT_PROFILES})[
            "items"
        ],
        "tools": tools,
        "risk_policy": services.risk_policy_service.settings_summary(),
        "trading_controls": {
            "paper_trading": "sandbox_only",
            "real_order": "blocked",
        },
        "runtime_config": services.repo.get_config(
            "runtime", {"config": DEFAULT_RUNTIME_CONFIG}
        ).get("config", DEFAULT_RUNTIME_CONFIG),
        "agent_runtime": services.copilot_service.deerflow.status().to_dict(),
        "data_provider": provider_router.status().to_dict(),
        "data_sources": services.repo.get_config("data_sources", DEFAULT_DATA_SOURCES),
        "available_data_providers": AVAILABLE_PROVIDERS,
        "intel_sources": services.repo.get_config(
            "intel_sources", DEFAULT_INTEL_SOURCES
        ),
        "available_intel_providers": AVAILABLE_INTEL_PROVIDERS,
        "available_sentiment_providers": AVAILABLE_SENTIMENT_PROVIDERS,
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
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings skills updated", "skills")
    return services.repo.set_config("skills", payload)


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
    result = services.repo.set_config("runtime", payload)
    # Auto-reconnect so the new config takes effect immediately
    status = services.copilot_service.reconnect_runtime()
    return {**result, "agent_runtime": status}


@router.put("/data-provider")
def put_data_provider(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings data provider updated", "data_sources")
    result = services.repo.set_config("data_sources", payload)
    # Clear provider cache so new config takes effect immediately
    provider_router.clear_cache()
    return result


@router.put("/intel-sources")
def put_intel_sources(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    services.audit_service.record("settings intel sources updated", "intel_sources")
    return services.repo.set_config("intel_sources", payload)


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
        provider_id = provider_config.get("provider", "mock")
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

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/channels", tags=["channels"])

_MASK = "********"
_SECRET_FIELDS = {"bot_token", "app_token", "bot_secret", "client_secret", "app_secret"}


def _mask(cfg: dict) -> dict:
    out: dict = {}
    for key, value in (cfg or {}).items():
        if isinstance(value, dict):
            out[key] = {k: (_MASK if k in _SECRET_FIELDS and v else v) for k, v in value.items()}
        else:
            out[key] = value
    return out


@router.get("/status")
def channels_status(services: AppServices = Depends(get_services)):
    svc = services.channel_service
    return svc.status() if svc else {"running": False, "channels": []}


@router.post("/connect-code")
def create_connect_code(request: Request, services: AppServices = Depends(get_services)):
    code = services.channel_binding_store.create_code()
    return {
        "code": code,
        "expires_in": 600,
        "instruction": "在已配置的 Bot 里发送 /connect <code>（Telegram 可用深链 /start <code>）完成绑定。",
    }


@router.get("/bindings")
def list_bindings(services: AppServices = Depends(get_services)):
    return {"items": services.channel_binding_store.list_bindings()}


@router.delete("/bindings/{channel}/{chat_id}")
def delete_binding(channel: str, chat_id: str, services: AppServices = Depends(get_services)):
    return {"deleted": services.channel_binding_store.unbind(channel, chat_id)}


@router.patch("/bindings/{channel}/{chat_id}")
def update_binding(channel: str, chat_id: str, payload: dict, services: AppServices = Depends(get_services)):
    """Update a binding's alert preference (which bound chats receive pushes)."""
    enabled = bool((payload or {}).get("alerts_enabled", True))
    updated = services.channel_binding_store.set_alerts_enabled(channel, chat_id, enabled)
    return {"updated": updated, "alerts_enabled": enabled}


@router.get("/config")
def get_config(services: AppServices = Depends(get_services)):
    return _mask(services.repo.get_config("channels", {}) or {})


@router.post("/config")
async def update_config(payload: dict, request: Request, services: AppServices = Depends(get_services)):
    """Merge-update the channels config, then hot-reload the channel service so
    newly-configured adapters actually connect (they are built at start time)."""
    current = dict(services.repo.get_config("channels", {}) or {})
    for key, value in (payload or {}).items():
        if isinstance(value, dict):
            merged = dict(current.get(key, {}) or {})
            for k, v in value.items():
                if k in _SECRET_FIELDS and v == _MASK:
                    continue  # keep existing secret
                merged[k] = v
            current[key] = merged
        else:
            current[key] = value
    services.repo.set_config("channels", current)
    if services.channel_service is not None:
        await services.channel_service.reload()
    return {**_mask(current), "service": services.channel_service.status() if services.channel_service else None}


@router.post("/restart")
async def restart_service(services: AppServices = Depends(get_services)):
    """Manually restart the channel service (re-read config, reconnect bots)."""
    if services.channel_service is not None:
        await services.channel_service.reload()
        return services.channel_service.status()
    return {"running": False, "channels": []}

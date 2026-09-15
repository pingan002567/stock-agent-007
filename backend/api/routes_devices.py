from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.deps import get_services
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/devices", tags=["devices"])


class APNsRegisterRequest(BaseModel):
    device_token: str = Field(min_length=8)
    environment: str = "sandbox"
    platform: str = "ios"
    bundle_id: str = "com.stockagent.app"


@router.post("/apns")
def register_apns(payload: APNsRegisterRequest, request: Request, services: AppServices = Depends(get_services)):
    saved = services.repo.upsert_apns_device(
        device_token=payload.device_token,
        environment=payload.environment,
        platform=payload.platform,
        bundle_id=payload.bundle_id,
    )
    services.audit_service.record("apns device registered", saved["device_token"][:12])
    return {"ok": True, **saved}


@router.delete("/apns/{device_token}")
def unregister_apns(device_token: str, request: Request, services: AppServices = Depends(get_services)):
    deleted = services.repo.delete_apns_device(device_token)
    if not deleted:
        raise HTTPException(status_code=404, detail="device not found")
    services.audit_service.record("apns device removed", device_token[:12])
    return {"deleted": True}


@router.get("/apns/status")
def apns_status(services: AppServices = Depends(get_services)):
    svc = getattr(services, "apns_push_service", None)
    if svc is None:
        return {"configured": False, "device_count": len(services.repo.list_apns_devices())}
    return svc.status()

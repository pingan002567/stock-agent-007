from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_services
from backend.app_services.setup_service import finish_setup, setup_status
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("")
def get_setup(request: Request, services: AppServices = Depends(get_services)):
    snapshot = services.llm_provider_service.snapshot()
    return setup_status(services.repo, snapshot)


@router.post("/finish")
def post_setup_finish(request: Request, services: AppServices = Depends(get_services)):
    result = finish_setup(services.repo)
    services.audit_service.record("setup finished", "workspace ready")
    snapshot = services.llm_provider_service.snapshot()
    result["model_connected"] = bool(snapshot.get("connected") or (snapshot.get("runtime") or {}).get("connected"))
    result["default_model"] = snapshot.get("default_model") or (snapshot.get("runtime") or {}).get("default_model")
    return result

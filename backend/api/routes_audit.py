from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import model_to_dict

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit")
def list_audit(
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.repo.list_audit(limit)
    return {"items": [model_to_dict(item) for item in items]}

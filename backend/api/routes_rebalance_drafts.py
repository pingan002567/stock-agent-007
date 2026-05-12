from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.app_services.rebalance_draft_service import (
    RebalanceDraftConflictError,
    RebalanceDraftExpiredError,
)
from backend.bootstrap import AppServices
from backend.schemas import RebalanceDraftCreateRequest, RebalanceDraftDecisionNoteRequest, model_to_dict

router = APIRouter(prefix="/api/rebalance-drafts", tags=["rebalance-drafts"])


@router.post("")
def create_rebalance_draft(
    payload: RebalanceDraftCreateRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    draft = services.rebalance_draft_service.create(payload, source_mode="http")
    return model_to_dict(draft)


@router.get("")
def list_rebalance_drafts(
    request: Request,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.rebalance_draft_service.list(symbol=symbol, status=status, limit=limit)
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/{draft_id}")
def get_rebalance_draft(draft_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.rebalance_draft_service.get(draft_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="rebalance draft not found") from exc


@router.post("/{draft_id}/confirm")
def confirm_rebalance_draft(
    draft_id: str,
    payload: RebalanceDraftDecisionNoteRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return model_to_dict(services.rebalance_draft_service.confirm(draft_id, payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="rebalance draft not found") from exc
    except RebalanceDraftExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RebalanceDraftConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{draft_id}/reject")
def reject_rebalance_draft(
    draft_id: str,
    payload: RebalanceDraftDecisionNoteRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return model_to_dict(services.rebalance_draft_service.reject(draft_id, payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="rebalance draft not found") from exc
    except RebalanceDraftConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

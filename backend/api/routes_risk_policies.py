from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import RiskPolicy, model_to_dict

router = APIRouter(prefix="/api/risk-policies", tags=["risk-policies"])


@router.get("")
def list_risk_policies(request: Request, services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.risk_policy_service.list_policies()]}


@router.post("")
def create_risk_policy(payload: RiskPolicy, request: Request, services: AppServices = Depends(get_services)):
    try:
        policy = services.risk_policy_service.create_policy(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return model_to_dict(policy)


@router.get("/active")
def get_active_risk_policy(request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.risk_policy_service.get_active_policy())
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="active risk policy not found") from exc


@router.get("/{policy_id}")
def get_risk_policy(policy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.risk_policy_service.get_policy(policy_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="risk policy not found") from exc


@router.put("/{policy_id}")
def update_risk_policy(
    policy_id: str,
    payload: RiskPolicy,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return model_to_dict(services.risk_policy_service.update_policy(policy_id, payload))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="risk policy not found") from exc


@router.post("/{policy_id}/activate")
def activate_risk_policy(policy_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.risk_policy_service.activate_policy(policy_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="risk policy not found") from exc

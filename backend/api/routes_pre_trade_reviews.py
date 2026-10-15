from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.app_services.pre_trade_review_service import PreTradeReviewConflictError
from backend.bootstrap import AppServices
from backend.schemas import PreTradeReviewCreateRequest, RebalanceDraftStatus, model_to_dict

router = APIRouter(prefix="/api/pre-trade-reviews", tags=["pre-trade-reviews"])


@router.post("")
def create_pre_trade_review(
    payload: PreTradeReviewCreateRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        draft = services.rebalance_draft_service.get(payload.draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="rebalance draft not found") from exc
    if draft.status != RebalanceDraftStatus.CONFIRMED_NO_EXECUTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"draft must be confirmed_no_execution before review, current={draft.status.value}",
        )
    try:
        review = services.pre_trade_review_service.create(
            draft_id=payload.draft_id,
            source_mode="http",
            strict_status=True,
        )
    except PreTradeReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return model_to_dict(review)


@router.get("")
def list_pre_trade_reviews(
    request: Request,
    draft_id: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.pre_trade_review_service.list(draft_id=draft_id, symbol=symbol, status=status, limit=limit)
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/{review_id}")
def get_pre_trade_review(review_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.pre_trade_review_service.get(review_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="pre-trade review not found") from exc

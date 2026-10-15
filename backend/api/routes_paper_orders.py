from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.app_services.paper_trading_service import PaperOrderConflictError
from backend.bootstrap import AppServices
from backend.schemas import PaperOrderCancelRequest, PaperOrderCreateRequest, model_to_dict

router = APIRouter(prefix="/api/paper-orders", tags=["paper-orders"])


@router.post("")
def create_paper_order(
    payload: PaperOrderCreateRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        order = services.paper_trading_service.create(payload.review_id, source_mode="http")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="pre-trade review not found") from exc
    except PaperOrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return model_to_dict(order)


@router.get("")
def list_paper_orders(
    request: Request,
    review_id: str | None = None,
    draft_id: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.paper_trading_service.list(
        review_id=review_id,
        draft_id=draft_id,
        symbol=symbol,
        status=status,
        limit=limit,
    )
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/{order_id}")
def get_paper_order(order_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.paper_trading_service.get(order_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="paper order not found") from exc


@router.post("/{order_id}/cancel")
def cancel_paper_order(
    order_id: str,
    payload: PaperOrderCancelRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return model_to_dict(services.paper_trading_service.cancel(order_id, payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="paper order not found") from exc
    except PaperOrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import ReviewInboxActionRequest, ReviewInboxSnoozeRequest, model_to_dict

router = APIRouter(prefix="/api/review-inbox", tags=["review-inbox"])


@router.get("")
def list_review_inbox(request: Request, services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.review_inbox_service.list_items()]}


@router.get("/summary")
def summarize_review_inbox(request: Request, services: AppServices = Depends(get_services)):
    return model_to_dict(services.review_inbox_service.summarize())


@router.post("/{item_key}/dismiss")
def dismiss_review_inbox_item(
    item_key: str,
    payload: ReviewInboxActionRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        state = services.review_inbox_service.dismiss(item_key, note=payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review inbox item not found") from exc
    return model_to_dict(state)


@router.post("/{item_key}/snooze")
def snooze_review_inbox_item(
    item_key: str,
    payload: ReviewInboxSnoozeRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        state = services.review_inbox_service.snooze(
            item_key,
            snoozed_until=payload.snoozed_until,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review inbox item not found") from exc
    return model_to_dict(state)


@router.post("/{item_key}/mark-done")
def mark_review_inbox_item_done(
    item_key: str,
    payload: ReviewInboxActionRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        state = services.review_inbox_service.mark_done(item_key, note=payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review inbox item not found") from exc
    return model_to_dict(state)

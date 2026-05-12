from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import get_services
from backend.app_services.decision_journal_service import (
    DecisionJournalCloseConflictError,
    DecisionJournalSnapshotConflictError,
    DecisionJournalSnapshotNotFoundError,
)
from backend.bootstrap import AppServices
from backend.schemas import DecisionJournalCloseRequest, DecisionJournalLinkSnapshotRequest

router = APIRouter(prefix="/api/decision-journal", tags=["decision-journal"])


@router.get("")
def list_decision_journal(
    request: Request,
    symbol: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    limit: int = 50,
    services: AppServices = Depends(get_services),
):
    items = services.decision_journal_service.list_entries(
        symbol=symbol,
        status=status,
        source_type=source_type,
        limit=limit,
    )
    return {"items": items}


@router.get("/summary")
def get_decision_journal_summary(
    request: Request,
    symbol: str | None = None,
    services: AppServices = Depends(get_services),
):
    return services.decision_journal_service.summarize_outcomes(symbol=symbol)


@router.get("/{entry_id}")
def get_decision_journal_entry(entry_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return services.decision_journal_service.get_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision journal entry not found") from exc


@router.post("/{entry_id}/link-snapshot")
def link_decision_journal_snapshot(
    entry_id: str,
    payload: DecisionJournalLinkSnapshotRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return services.decision_journal_service.link_snapshot(entry_id, payload.snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision journal entry not found") from exc
    except DecisionJournalSnapshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"paper portfolio snapshot not found: {exc}") from exc
    except DecisionJournalSnapshotConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{entry_id}/close")
def close_decision_journal_entry(
    entry_id: str,
    payload: DecisionJournalCloseRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        return services.decision_journal_service.close_entry(entry_id, payload.close_note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision journal entry not found") from exc
    except DecisionJournalCloseConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

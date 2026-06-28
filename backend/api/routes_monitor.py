from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend.agent_runtime.stream_adapter import to_sse
from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import model_to_dict

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/events")
def monitor_events(
    symbol: str | None = None,
    severity: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    services: AppServices = Depends(get_services),
):
    svc = services.monitor_service
    # Real DB-level pagination: total is a full COUNT(*), not len() of a
    # truncated page. allow_fallback=False keeps synthetic demo events out of
    # the user-facing list and its counts.
    total = svc.count_events(symbol=symbol, severity=severity, allow_fallback=False)
    items = svc.list_events(
        symbol=symbol,
        severity=severity,
        limit=page_size,
        offset=(page - 1) * page_size,
        allow_fallback=False,
    )
    return {
        "items": [model_to_dict(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/status")
def monitor_status(services: AppServices = Depends(get_services)):
    return model_to_dict(services.monitor_service.get_status())


@router.get("/rules")
def monitor_rules(services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.monitor_service.list_rules()]}


@router.post("/start")
async def start_monitor(request: Request, services: AppServices = Depends(get_services)):
    status = services.monitor_service.start()
    await services.monitor_service.start_loop()
    return model_to_dict(status)


@router.post("/pause")
async def pause_monitor(request: Request, services: AppServices = Depends(get_services)):
    status = services.monitor_service.pause()
    await services.monitor_service.stop_loop()
    return model_to_dict(status)


@router.post("/rules")
def update_rules(payload: dict, request: Request, services: AppServices = Depends(get_services)):
    return model_to_dict(services.monitor_service.upsert_rule(payload))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, services: AppServices = Depends(get_services)):
    return {"deleted": services.monitor_service.delete_rule(rule_id)}


@router.post("/evaluate-once")
def evaluate_once(payload: dict | None = None, services: AppServices = Depends(get_services)):
    payload = payload or {}
    return services.monitor_service.evaluate_once(
        source=str(payload.get("source") or "manual"),
        force=bool(payload.get("force", False)),
    )


@router.post("/feedback")
def monitor_feedback(payload: dict, services: AppServices = Depends(get_services)):
    """Report whether a monitor event was useful (for accuracy-based fatigue suppression)."""
    rule_id = str(payload.get("rule_id", ""))
    was_useful = bool(payload.get("was_useful", False))
    if rule_id:
        services.monitor_service.record_accuracy(rule_id, was_useful)
    return {"ok": True}


@router.get("/stream")
def monitor_stream(
    once: bool = Query(default=False, description="Emit a single snapshot then close (no long-lived stream)"),
    services: AppServices = Depends(get_services),
):
    return StreamingResponse(
        to_sse(services.monitor_service.stream_snapshot(once=once)),
        media_type="text/event-stream",
    )

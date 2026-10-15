from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])


@router.get("")
def list_scheduled_tasks(request: Request, services: AppServices = Depends(get_services)):
    return {"items": services.scheduler_service.list_tasks()}


@router.post("")
def upsert_scheduled_task(
    payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    try:
        return services.scheduler_service.upsert_task(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{task_id}/toggle")
def toggle_scheduled_task(
    task_id: str, payload: dict, request: Request, services: AppServices = Depends(get_services)
):
    try:
        return services.scheduler_service.set_enabled(task_id, bool(payload.get("enabled")))
    except KeyError:
        raise HTTPException(status_code=404, detail="scheduled task not found")


@router.post("/{task_id}/run-now")
async def run_scheduled_task_now(
    task_id: str, request: Request, services: AppServices = Depends(get_services)
):
    try:
        return await services.scheduler_service.run_task_now(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scheduled task not found")


@router.delete("/{task_id}")
def delete_scheduled_task(
    task_id: str, request: Request, services: AppServices = Depends(get_services)
):
    services.scheduler_service.delete_task(task_id)
    return {"ok": True}

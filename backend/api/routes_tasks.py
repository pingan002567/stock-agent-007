from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.agent_runtime.stream_adapter import encode_sse
from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import SSEEvent, model_to_dict

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_detail_payload(services: AppServices, task_id: str):
    task = services.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    payload = model_to_dict(task)
    payload["tool_executions"] = [model_to_dict(item) for item in services.repo.list_tool_executions(task_id=task_id)]
    return payload


@router.get("")
def list_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    services: AppServices = Depends(get_services),
):
    all_items = services.repo.list_tasks()
    total = len(all_items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_items = all_items[start_idx:end_idx]
    return {
        "items": [model_to_dict(item) for item in paginated_items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/{task_id}")
def get_task(task_id: str, request: Request, services: AppServices = Depends(get_services)):
    return _task_detail_payload(services, task_id)


@router.get("/{task_id}/stream")
def stream_task(task_id: str, request: Request, services: AppServices = Depends(get_services)):
    task = services.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    tool_executions = services.repo.list_tool_executions(task_id=task_id)

    async def events():
        yield encode_sse(
            SSEEvent(
                run_id=task.run_id or "run_none",
                task_id=task.task_id,
                type="reasoning",
                payload={"phase": "task_snapshot", "task": model_to_dict(task)},
            )
        )
        for execution in tool_executions:
            payload = {
                "execution_id": execution.execution_id,
                "call_id": execution.call_id,
                "tool": execution.tool,
                "domain": execution.domain,
                "status": execution.status,
                "authority_level": execution.authority_level,
                "arguments": execution.arguments,
                "source_mode": execution.source_mode,
                "evidence_refs": execution.evidence_refs,
                "result_summary": execution.result_summary,
            }
            event_type = "tool_result"
            if execution.status != "succeeded":
                event_type = "error"
                payload["error"] = execution.error
            yield encode_sse(
                SSEEvent(
                    run_id=execution.run_id or task.run_id or "run_none",
                    task_id=task.task_id,
                    type=event_type,
                    payload=payload,
                )
            )
        yield encode_sse(
            SSEEvent(
                run_id=task.run_id or "run_none",
                task_id=task.task_id,
                type="final",
                payload={"status": task.status, "tool_execution_count": len(tool_executions)},
            )
        )

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{task_id}/retry")
def retry_task(task_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        task = services.task_service.retry(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    services.audit_service.record("task retry", task.task_id)
    return model_to_dict(task)

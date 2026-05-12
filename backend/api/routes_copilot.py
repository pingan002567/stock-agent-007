from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.agent_runtime.stream_adapter import to_sse
from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.app_services.permission_guard import PermissionDenied
from backend.schemas import (
    CopilotRequest,
    CopilotSessionCreateRequest,
    CopilotSessionMessageRequest,
    CopilotSessionUpdateRequest,
    model_to_dict,
)

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


@router.get("/sessions")
def list_sessions(request: Request, services: AppServices = Depends(get_services)):
    return {"items": [model_to_dict(item) for item in services.copilot_service.list_sessions()]}


@router.post("/sessions")
def create_session(payload: CopilotSessionCreateRequest, request: Request, services: AppServices = Depends(get_services)):
    return model_to_dict(services.copilot_service.create_session(payload))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        session = services.copilot_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return model_to_dict(session)


@router.put("/sessions/{session_id}")
def update_session(session_id: str, payload: CopilotSessionUpdateRequest, request: Request, services: AppServices = Depends(get_services)):
    try:
        session = services.copilot_service.update_session(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return model_to_dict(session)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        services.copilot_service.delete_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return {"status": "deleted"}


@router.get("/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
    run_id: str | None = None,
):
    try:
        items = services.copilot_service.list_messages(session_id, run_id=run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return {"items": [model_to_dict(item) for item in items]}


@router.post("/sessions/{session_id}/messages")
def create_session_message(
    session_id: str,
    payload: CopilotSessionMessageRequest,
    request: Request,
    services: AppServices = Depends(get_services),
):
    try:
        run = services.copilot_service.create_session_run(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except (PermissionDenied, PermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return model_to_dict(run)


@router.get("/sessions/{session_id}/stream/{run_id}")
def stream_session_run(session_id: str, run_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        services.copilot_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    if not services.copilot_service.has_run(run_id, session_id=session_id):
        raise HTTPException(status_code=404, detail="copilot run not found")

    return StreamingResponse(
        to_sse(services.copilot_service.stream_run(run_id, session_id=session_id)),
        media_type="text/event-stream",
    )


@router.post("/chat")
def chat(payload: CopilotRequest, request: Request, services: AppServices = Depends(get_services)):
    try:
        run = services.copilot_service.create_run(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except (PermissionDenied, PermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return model_to_dict(run)


@router.get("/stream/{run_id}")
def stream(run_id: str, request: Request, services: AppServices = Depends(get_services)):
    if not services.copilot_service.has_run(run_id):
        raise HTTPException(status_code=404, detail="copilot run not found")
    return StreamingResponse(to_sse(services.copilot_service.stream_run(run_id)), media_type="text/event-stream")

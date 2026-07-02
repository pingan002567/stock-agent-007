from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
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


# 允许的研报/资料类型：PDF/Office 会被 DeerFlow 自动转 Markdown，纯文本直接可读；
# 图片（K线截图/研报图表）由 view_image 工具读取，需模型 supports_vision
_UPLOAD_ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".md", ".txt", ".csv",
    ".png", ".jpg", ".jpeg", ".webp",
}
_UPLOAD_MAX_BYTES = 50 * 1024 * 1024


@router.post("/sessions/{session_id}/uploads")
def upload_session_files(
    session_id: str,
    files: list[UploadFile],
    request: Request,
    services: AppServices = Depends(get_services),
):
    """上传研报/年报等资料到会话线程，供 AI 在后续对话中直接读取。"""
    try:
        services.copilot_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    if not files:
        raise HTTPException(status_code=422, detail="no files provided")
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in _UPLOAD_ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported file type: {f.filename}（支持 {'/'.join(sorted(_UPLOAD_ALLOWED_EXTENSIONS))}）",
            )

    with tempfile.TemporaryDirectory(prefix="copilot-upload-") as tmp_dir:
        local_paths: list[str] = []
        for f in files:
            # basename 防路径穿越；DeerFlow 侧 claim_unique_filename 再做去重
            dest = Path(tmp_dir) / Path(f.filename or "upload.bin").name
            size = 0
            with dest.open("wb") as out:
                while chunk := f.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > _UPLOAD_MAX_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"file too large: {f.filename}（上限 50MB）",
                        )
                    out.write(chunk)
            local_paths.append(str(dest))
        result = services.copilot_service.deerflow.upload_files(session_id, local_paths)

    if not result.get("supported"):
        raise HTTPException(status_code=409, detail=result)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result)
    return result


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

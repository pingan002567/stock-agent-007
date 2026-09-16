from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.agent_runtime.stream_adapter import SSE_HEADERS, to_sse
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return model_to_dict(session)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        services.copilot_service.delete_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return {"status": "deleted"}


# 按 DeerFlow 实际文件能力三档放行（对齐其实现但不 import 其内部）：
# 1) Office/PDF —— upload_files 自动转 Markdown（对应 file_conversion.CONVERTIBLE_EXTENSIONS）
# 2) 图片 —— view_image 工具可读（仅 jpg/png/webp，gif 不支持），需模型 supports_vision
# 3) 任意 UTF-8 文本 —— read_file/grep 直接可读，不限扩展名，按内容嗅探判定
# 其余二进制（zip/sqlite/音视频…）沙箱只读工具读不了，拒收
_CONVERTIBLE_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
_TEXT_SNIFF_BYTES = 64 * 1024
_UPLOADS_UNSUPPORTED_DETAIL = (
    "当前 AI 运行时不支持读附件（需要 DeerFlow direct/embedded，不是 stub）"
)


def _looks_like_utf8_text(sample: bytes) -> bool:
    """含 NUL 或非 UTF-8 视为二进制；嗅探窗口截断多字节字符尾部时放行。"""
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        # UTF-8 单字符最长 4 字节，仅当解码错误落在窗口末尾（截断导致）才算文本
        return exc.start >= len(sample) - 3
    return True


def _require_session(services: AppServices, session_id: str) -> None:
    try:
        services.copilot_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


def _is_safe_upload_filename(filename: str) -> bool:
    if not filename or filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return Path(filename).name == filename


def _present_uploads(files: list[dict]) -> list[dict]:
    """Chip-facing listing: hide companion .md generated from Office/PDF."""
    names = {str(item.get("filename") or "") for item in files}
    presented: list[dict] = []
    for item in files:
        name = str(item.get("filename") or "")
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        stem = Path(name).stem
        if suffix == ".md" and any(f"{stem}{ext}" in names for ext in _CONVERTIBLE_EXTENSIONS):
            continue
        markdown_file = item.get("markdown_file")
        if not markdown_file and suffix in _CONVERTIBLE_EXTENSIONS and f"{stem}.md" in names:
            markdown_file = f"{stem}.md"
        presented.append(
            {
                "filename": name,
                "size": int(item.get("size") or 0),
                "markdown_file": markdown_file or None,
            }
        )
    return presented


def _raise_if_upload_op_failed(result: dict, *, missing_as_404: bool = False) -> None:
    if not result.get("supported"):
        raise HTTPException(status_code=409, detail=_UPLOADS_UNSUPPORTED_DETAIL)
    err = result.get("error")
    if not err:
        return
    text = str(err)
    lower = text.lower()
    if missing_as_404 and "not found" in lower:
        raise HTTPException(status_code=404, detail="file not found")
    if "traversal" in lower or "unsafe" in lower:
        raise HTTPException(status_code=400, detail="invalid filename")
    raise HTTPException(status_code=500, detail=text)


@router.post("/sessions/{session_id}/uploads")
def upload_session_files(
    session_id: str,
    files: list[UploadFile],
    request: Request,
    services: AppServices = Depends(get_services),
):
    """上传文件到会话线程，供 AI 在后续对话中直接读取。

    接收范围即 DeerFlow 可消费范围：Office/PDF（自动转 Markdown）、
    图片（view_image）、任意 UTF-8 文本（read_file/grep，扩展名不限）。
    """
    _require_session(services, session_id)
    if not files:
        raise HTTPException(status_code=422, detail="no files provided")

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
            # Office/PDF/图片按扩展名放行；其余落盘后嗅探内容，仅拒真二进制
            suffix = dest.suffix.lower()
            if suffix not in _CONVERTIBLE_EXTENSIONS and suffix not in _IMAGE_EXTENSIONS:
                with dest.open("rb") as fh:
                    sample = fh.read(_TEXT_SNIFF_BYTES)
                if not _looks_like_utf8_text(sample):
                    raise HTTPException(
                        status_code=415,
                        detail=(
                            f"unsupported binary file: {f.filename}"
                            "（AI 可读：任意文本文件、PDF/Word/Excel/PPT、png/jpg/webp 图片）"
                        ),
                    )
            local_paths.append(str(dest))
        result = services.copilot_service.deerflow.upload_files(session_id, local_paths)

    if not result.get("supported"):
        raise HTTPException(status_code=409, detail=_UPLOADS_UNSUPPORTED_DETAIL)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result)
    return result


@router.get("/sessions/{session_id}/uploads")
def list_session_uploads(
    session_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    """列出会话线程里已上传、AI 下一轮可读的附件。

    stub 运行时返回 200 ``{supported: false, files: [], count: 0}``，
    方便前端禁用「+」而不是当成错误弹窗。
    """
    _require_session(services, session_id)
    result = services.copilot_service.deerflow.list_uploads(session_id)
    if not result.get("supported"):
        return {"supported": False, "files": [], "count": 0}
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result)
    files = _present_uploads(list(result.get("files") or []))
    return {"supported": True, "files": files, "count": len(files)}


@router.delete("/sessions/{session_id}/uploads/{filename}")
def delete_session_upload(
    session_id: str,
    filename: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    """删除会话附件。Office/PDF 会顺带删掉转换出的 companion ``.md``。"""
    _require_session(services, session_id)
    if not _is_safe_upload_filename(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    result = services.copilot_service.deerflow.delete_upload(session_id, filename)
    _raise_if_upload_op_failed(result, missing_as_404=True)
    return result


@router.get("/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
    run_id: str | None = None,
    limit_turns: int | None = Query(default=None, ge=1, le=200),
    before: str | None = None,
):
    try:
        if limit_turns is not None and run_id is None:
            page = services.copilot_service.list_messages_page(
                session_id, limit_turns=limit_turns, before=before
            )
            return {
                "items": [model_to_dict(item) for item in page["items"]],
                "has_more": page["has_more"],
                "next_before": page["next_before"],
            }
        items = services.copilot_service.list_messages(session_id, run_id=run_id)
        return {"items": [model_to_dict(item) for item in items]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


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
        headers=SSE_HEADERS,
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
    return StreamingResponse(
        to_sse(services.copilot_service.stream_run(run_id)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

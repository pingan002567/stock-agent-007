"""Optional shared-secret gate for remote / mobile clients.

Local desktop keeps working when WORKBENCH_ACCESS_TOKEN is unset.
When set, REST needs X-Workbench-Token (or Bearer); SSE may use ?access_token=.
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_HEADER = "x-workbench-token"
TOKEN_QUERY = "access_token"
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:1420",
    "tauri://localhost",
    "https://tauri.localhost",
    "capacitor://localhost",
    "ionic://localhost",
    "http://localhost",
    "https://localhost",
]


def configured_token() -> str:
    return os.getenv("WORKBENCH_ACCESS_TOKEN", "").strip()


def cors_origin_list() -> list[str]:
    raw = os.getenv("WORKBENCH_CORS_ORIGINS")
    if raw is None:
        return ["*"] if not configured_token() else list(DEFAULT_CORS_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


def tokens_match(provided: str, expected: str) -> bool:
    if not expected or not provided:
        return False
    left = provided.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def is_sse_path(path: str) -> bool:
    if path == "/api/monitor/stream" or path.startswith("/api/monitor/stream/"):
        return True
    if not path.startswith("/api/copilot/"):
        return False
    return "/stream/" in path or path.endswith("/stream")


def extract_token(request: Request, *, allow_query: bool) -> str:
    header = request.headers.get(TOKEN_HEADER, "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if allow_query:
        return (request.query_params.get(TOKEN_QUERY) or "").strip()
    return ""


class AccessAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        expected = configured_token()
        path = request.url.path
        request.state.workbench_authorized = False
        if not expected or request.method == "OPTIONS" or not path.startswith("/api/"):
            if expected and path.startswith("/api/"):
                provided = extract_token(request, allow_query=is_sse_path(path))
                request.state.workbench_authorized = tokens_match(provided, expected)
            return await call_next(request)

        allow_query = is_sse_path(path)
        provided = extract_token(request, allow_query=allow_query)
        authorized = tokens_match(provided, expected)
        request.state.workbench_authorized = authorized

        if path == "/api/health" or path.startswith("/api/health/"):
            return await call_next(request)

        if not authorized:
            return JSONResponse({"detail": "未授权：请填写访问令牌"}, status_code=401)
        return await call_next(request)

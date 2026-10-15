"""Heuristic error classification for Copilot run logging.

Extracted from copilot_service.py. These map exception text / error payloads to
coarse categories and user-facing hints.

NOTE: these are heuristic substring matches on exception text and are
locale/SDK-fragile; centralized here so they can be unit-tested and later
replaced by structured error codes from the tool-bridge / adapter boundary.
"""
from __future__ import annotations

from typing import Any


def categorize_error(exc: Exception) -> str:
    """Map a stream-run exception to a coarse error category for the run log."""
    error_msg = str(exc).lower()
    if "401" in error_msg or "unauthorized" in error_msg:
        return "auth_error"
    if "429" in error_msg or "rate limit" in error_msg:
        return "rate_limit"
    if "timeout" in error_msg or "timed out" in error_msg:
        return "timeout"
    if "recursion limit" in error_msg or "graph_recursion_limit" in error_msg:
        return "recursion_limit"
    if "skill filesystem isolation" in error_msg or "localsandboxprovider" in error_msg:
        return "sandbox_isolation"
    if "tool" in error_msg or "execution" in error_msg:
        return "tool_error"
    if "permission" in error_msg or "denied" in error_msg:
        return "auth_error"
    return "stream_run"


def classify_outcome(error_payload: dict[str, Any] | None) -> str:
    if not error_payload:
        return "success"
    error_msg = str(error_payload.get("error", "")).lower()
    if "timeout" in error_msg or "timed out" in error_msg:
        return "timeout"
    return "error"


def error_hint(error_payload: dict[str, Any]) -> str | None:
    error_msg = str(error_payload.get("error", ""))
    lower = error_msg.lower()
    if "draft must be confirmed" in error_msg:
        return "DRAFT_NOT_CONFIRMED"
    if "requires an explicit confirmed draft_id" in error_msg:
        return "MISSING_DRAFT_ID"
    if "draft is already" in error_msg and "confirmed" in error_msg:
        return "DRAFT_ALREADY_CONFIRMED"
    if "expired" in error_msg:
        return "DRAFT_EXPIRED"
    if "permission" in lower or "denied" in lower:
        return "PERMISSION_DENIED"
    if "skill filesystem isolation" in lower or "localsandboxprovider" in lower:
        return "SANDBOX_SKILL_ISOLATION"
    if "recursion limit" in lower:
        return "GRAPH_RECURSION_LIMIT"
    return None


def user_facing_error(error_msg: str) -> str:
    """Map raw runtime exceptions to short Chinese copy for the chat bubble."""
    lower = (error_msg or "").lower()
    if "skill filesystem isolation" in lower or (
        "localsandboxprovider" in lower and "cannot enforce" in lower
    ):
        return (
            "本机已开 host bash，无法做技能目录隔离，部分子代理沙箱策略失败。"
            "可改用 Docker 沙箱，或设 WORKBENCH_SANDBOX_ALLOW_HOST_BASH=0 后重启；"
            "改技能请用 skill_manage。"
        )
    if "recursion limit" in lower:
        return (
            "这轮分析步骤过多，已触达图递归上限。"
            "请拆成更小的问题重试；或提高 WORKBENCH_AI_RECURSION_LIMIT_SUBAGENT 后重启后端。"
        )
    return error_msg

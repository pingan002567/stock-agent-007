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
    if "draft must be confirmed" in error_msg:
        return "DRAFT_NOT_CONFIRMED"
    if "requires an explicit confirmed draft_id" in error_msg:
        return "MISSING_DRAFT_ID"
    if "draft is already" in error_msg and "confirmed" in error_msg:
        return "DRAFT_ALREADY_CONFIRMED"
    if "expired" in error_msg:
        return "DRAFT_EXPIRED"
    if "permission" in error_msg.lower() or "denied" in error_msg.lower():
        return "PERMISSION_DENIED"
    return None

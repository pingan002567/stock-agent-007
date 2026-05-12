from __future__ import annotations

from typing import Any

CANONICAL_EXECUTION_GUARD = {
    "auto_trade": False,
    "place_real_order_enabled": False,
    "paper_trading": "sandbox_only",
    "real_order": "blocked",
}


def canonical_execution_guard() -> dict[str, Any]:
    return dict(CANONICAL_EXECUTION_GUARD)


def extract_execution_guard(output: object) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None
    guard = output.get("execution_guard")
    if not isinstance(guard, dict):
        return None
    return dict(guard)


def is_canonical_execution_guard(guard: object) -> bool:
    if not isinstance(guard, dict):
        return False
    return guard == CANONICAL_EXECUTION_GUARD

"""Token-cost estimation for Copilot runs.

Extracted from copilot_service.py so the pricing table and rate-matching logic
can be unit-tested and updated independently of the streaming orchestration.
"""
from __future__ import annotations


ESTIMATED_COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "deepseek-chat": {"input": 0.0005, "output": 0.002},
}


def _resolve_rates(model_name: str | None) -> dict[str, float]:
    """Match model name to a pricing entry.

    Real model ids often carry date/variant suffixes (e.g. ``gpt-4o-2024-08-06``,
    ``deepseek-chat-v2``), so fall back to a longest-prefix match before the
    default rates instead of requiring an exact key.
    """
    name = (model_name or "").lower()
    if name in ESTIMATED_COST_PER_1K_TOKENS:
        return ESTIMATED_COST_PER_1K_TOKENS[name]
    matches = [key for key in ESTIMATED_COST_PER_1K_TOKENS if name.startswith(key)]
    if matches:
        return ESTIMATED_COST_PER_1K_TOKENS[max(matches, key=len)]
    return ESTIMATED_COST_PER_1K_TOKENS["gpt-4o-mini"]


def _estimate_cost(
    input_tokens: int, output_tokens: int, model_name: str | None = None
) -> float:
    rates = _resolve_rates(model_name)
    input_cost = (input_tokens / 1000) * rates["input"]
    output_cost = (output_tokens / 1000) * rates["output"]
    return round(input_cost + output_cost, 6)

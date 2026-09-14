from __future__ import annotations

from typing import Any, Dict

from backend.agent_runtime.disclaimer import RESEARCH_DISCLAIMER


class ResultNormalizer:
    """Gateway-only final polish. Does not invent confidence or counter-arguments."""

    def normalize_final(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            result = {"conclusion": str(result or "")}
        result.setdefault("disclaimer", RESEARCH_DISCLAIMER)
        return result

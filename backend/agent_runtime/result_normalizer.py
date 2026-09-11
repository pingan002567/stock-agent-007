from __future__ import annotations

from typing import Any, Dict


class ResultNormalizer:
    """Gateway-only final polish. Does not invent confidence or counter-arguments."""

    def normalize_final(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            result = {"conclusion": str(result or "")}
        result.setdefault("disclaimer", "仅供研究，不构成投资建议。")
        return result

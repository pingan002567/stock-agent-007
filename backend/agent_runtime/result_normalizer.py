from __future__ import annotations

from typing import Any, Dict


class ResultNormalizer:
    def normalize_final(self, result: Dict[str, Any]) -> Dict[str, Any]:
        result.setdefault("disclaimer", "仅供研究，不构成投资建议。")
        result.setdefault("confidence", "medium")
        result.setdefault("counter_reasons", ["真实数据源接入后需复核。"])
        return result

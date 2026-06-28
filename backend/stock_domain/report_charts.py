"""Text-based chart primitives for report content.

Pure, dependency-free helpers that render small "charts" as Unicode text so the
same markdown renders identically in the web preview (MarkdownRenderer) and in
the exported PDF (the bundled NotoSansSC font covers every glyph used here:
block elements █░, sparkline bars ▁▂▃▄▅▆▇, and ▲▼ markers).
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

_SPARK = "▁▂▃▄▅▆▇█"


def _finite(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def bar(value: object, vmax: float = 100.0, width: int = 16) -> str:
    """A horizontal gauge: ``████████░░░░░░░░``. ``value`` is clamped to [0, vmax]."""
    v = _finite(value)
    if v is None or vmax <= 0:
        return "░" * width
    ratio = max(0.0, min(v / vmax, 1.0))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def gauge(value: object, vmax: float = 100.0, width: int = 16, suffix: str = "") -> str:
    """``bar`` plus the numeric value, e.g. ``██████░░░░ 62``."""
    v = _finite(value)
    label = "N/A" if v is None else (f"{v:g}{suffix}")
    return f"{bar(value, vmax, width)} {label}"


def pct_marker(change: object, decimals: int = 2) -> str:
    """Signed change with a direction marker: ``▲ +1.20%`` / ``▼ -0.80%``."""
    v = _finite(change)
    if v is None:
        return "— N/A"
    if v > 0:
        return f"▲ +{v:.{decimals}f}%"
    if v < 0:
        return f"▼ {v:.{decimals}f}%"
    return f"— {v:.{decimals}f}%"


def sparkline(values: Iterable[object]) -> str:
    """A compact trend line, e.g. ``▁▂▄▅▇█``. Non-finite points are dropped."""
    finite = [f for f in (_finite(v) for v in values) if f is not None]
    if not finite:
        return ""
    lo, hi = min(finite), max(finite)
    span = (hi - lo) or 1.0
    return "".join(_SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))] for v in finite)


def table(headers: list[str], rows: list[list[object]]) -> list[str]:
    """Build markdown table lines (header + separator + rows).

    Returned as a list of strings ready to splice into the content line list.
    Cells are stringified; ``None`` becomes ``—``.
    """
    def cell(value: object) -> str:
        if value is None or value == "":
            return "—"
        return str(value)

    head = "| " + " | ".join(cell(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return [head, sep, *body]


def fmt(value: object, decimals: int = 2, suffix: str = "") -> str:
    """Human-friendly number formatting; passes through non-numbers unchanged."""
    v = _finite(value)
    if v is None:
        return "—" if value in (None, "") else str(value)
    if abs(v) >= 1_0000_0000:
        return f"{v / 1_0000_0000:.{decimals}f} 亿{suffix}"
    if abs(v) >= 1_0000:
        return f"{v / 1_0000:.{decimals}f} 万{suffix}"
    if v == int(v):
        return f"{int(v)}{suffix}"
    return f"{v:.{decimals}f}{suffix}"

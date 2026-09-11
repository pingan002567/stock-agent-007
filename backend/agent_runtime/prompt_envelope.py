"""Render the user turn for DeerFlow: original message plus a tiny context header.

Lead Agent is the only orchestrator. This module must not wrap the user message
in a JSON envelope, declare skill budgets, or inject session/tool ledgers.
"""

from __future__ import annotations

from typing import Any

LEAD_RUNTIME_CONSTRAINTS = [
    "你是 Stock Agent(个人 AI 投研工作台)的内置助手;被问及身份时如此自称,不要自称 DeerFlow。",
    "只输出研究、风险和拟单建议；不要尝试真实交易。",
    "简单事实问题直接调用域工具回答，不要为此 task() 委派子代理。",
    "深度研究、调仓、回测才按需委派技能；调仓收口前必须委派 risk-officer。",
    "不要请求或泄露 secret、环境变量、配置原文或本机路径。",
    "不要要求完整持仓、完整自选、完整历史、完整报告或工具台账明细。",
]


def build_prompt_envelope(
    *,
    user_message: str,
    skill_trace: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Metadata-only view of the turn. Not sent to the model as JSON."""
    del skill_trace, budget
    ctx = context or {}
    symbol = ctx.get("symbol") or ctx.get("anchor_symbol") or ""
    if not symbol and isinstance(ctx.get("symbol_summary"), dict):
        symbol = ctx["symbol_summary"].get("symbol") or ""
    return {
        "user_message": user_message,
        "current_page": ctx.get("page") or "overview",
        "anchor_symbol": symbol or None,
        "authority_level": ctx.get("_authority_level"),
    }


def render_prompt_envelope(
    *,
    user_message: str,
    skill_trace: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> str:
    """User text stays verbatim; page/symbol/authority are a short XML header."""
    meta = build_prompt_envelope(
        user_message=user_message,
        skill_trace=skill_trace,
        context=context,
        budget=budget,
    )
    lines = ["<workbench_context>"]
    lines.append(f"page: {meta['current_page']}")
    if meta.get("anchor_symbol"):
        lines.append(f"symbol: {meta['anchor_symbol']}")
    if meta.get("authority_level"):
        lines.append(f"authority: {meta['authority_level']}")
    for rule in LEAD_RUNTIME_CONSTRAINTS:
        lines.append(f"- {rule}")
    lines.append("</workbench_context>")
    lines.append("")
    lines.append(user_message)
    return "\n".join(lines)


def is_usable_session_title(title: str | None) -> bool:
    """Reject titles leaked from the prompt envelope / JSON wrappers.

    DeerFlow often titles a thread from the first HumanMessage. Our first message
    starts with ``<workbench_context>…``, so raw truncations must not become the
    sidebar session title.
    """
    if not isinstance(title, str):
        return False
    text = title.strip()
    if not text:
        return False
    if text.startswith(("{", "[", "<")):
        return False
    lowered = text.lower()
    if "workbench_context" in lowered:
        return False
    if "envelope_version" in lowered:
        return False
    # Truncated envelope body without the opening tag (e.g. "page: chat authority…")
    if lowered.startswith("page:") and ("authority" in lowered or "symbol:" in lowered):
        return False
    return True

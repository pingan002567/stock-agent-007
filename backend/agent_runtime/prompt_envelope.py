"""Render the user turn for DeerFlow: original message plus a tiny context header.

Lead Agent is the only orchestrator. This module must not wrap the user message
in a JSON envelope, declare skill budgets, or inject session/tool ledgers.
"""

from __future__ import annotations

import re
from typing import Any

LEAD_RUNTIME_CONSTRAINTS = [
    "你是 Stock Agent(个人 AI 投研工作台)的内置助手;被问及身份时如此自称,不要自称 DeerFlow。",
    "可以给出目标价与买卖/仓位操作指令，但必须声明不构成投资建议；禁止真实下单与自动交易。",
    "简单事实问题直接调用域工具回答，不要为此 task() 委派子代理。",
    "数据源双通道：自选/持仓/盯盘由系统缓存（Mode B），不要为刷仪表盘反复打源。"
    "快捷工具返回 degraded=true、available_industries_sample 为空、或缺关键字段时："
    "必须先 list_data_sources，再 invoke_data_capability 换可用 provider（行业优先 tonghuashun；"
    "北向/两融/龙虎榜/解禁用 tushare 对应 capability）。禁止编造数字，禁止索要或回显 Token。"
    "仍失败再用 web_search 并标精度有限。",
    "深度研究、调仓、回测才按需委派技能；调仓收口前必须委派 risk-officer。",
    "可用 write_file/str_replace/bash；改已安装技能内容用 skill_manage（写 DeerFlow 用户技能目录），不要用 write_file/bash 改 SKILL.md 或仓库 skills/custom。",
    "技能启停用 update_skill；查看用 list_skills。MCP 用 list_mcp_servers / upsert_mcp_server / remove_mcp_server（DeerFlow 原生配置）。不要用 update_agent 改 skills 或 MCP。",
    "定时值班任务用 list_scheduled_tasks / toggle_scheduled_task / upsert_scheduled_task / run_scheduled_task_now；日程格式 daily@HH:MM / weekly@N@HH:MM / every@Nm。run_now 后台执行，勿同步等待，完成后用 list 看 last_status。",
    "用户要求改人格、纪律或行为设定时，用 update_agent 提交完整 soul（基于当前 SOUL 改完再整篇写入，下轮生效）。不要用 write_file/bash 改 SOUL.md，也不要用 update_agent 改 tool_groups、skills 或 model。",
    "不要请求或泄露 secret、环境变量、配置原文或本机敏感路径。MCP env 仅在工具参数中传入，勿在回复中回显明文。",
    "不要要求完整持仓、完整自选、完整历史、完整报告或工具台账明细。",
    "行情结果里 stale=true 表示日K未到应有交易日。用户要求刷新，或 stale 且问题依赖现价/今日量价时，对同一标的最多调用一次 refresh_market_data；不要每次 get_stock_context 都打穿缓存。degraded 或缺字段不要编造。北向/融资融券/龙虎榜/解禁看 get_market_structure.extra；某块 degraded 或在 missing 里时写 reason，不能用行业新闻代替个股龙虎榜。research_status 为未生成研报时，score 0 不是评分。非交易日不是缺 K 线。",
    "收口免责固定句：可含目标价与操作指令，仅供研究参考，不构成投资建议。",
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


def scheduled_task_session_title(message: str | None) -> str | None:
    """Sidebar title for a duty-run opening line ``[定时任务·盘前简报 09-14 08:30]``.

    Raw brackets are rejected as envelope leaks, so the stored title must be the
    task name (plus date) rather than the message prefix.
    """
    if not isinstance(message, str):
        return None
    match = re.match(r"^\[定时任务·([^\s\]]+)\s+(\d{2}-\d{2})", message.strip())
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)}"


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

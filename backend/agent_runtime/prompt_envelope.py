from __future__ import annotations

import json
from typing import Any

from backend.agent_runtime import skill_specs

_RESEARCH_SKILLS = {"stock-researcher", "valuation-analyst", "catalyst-tracker"}


SAFE_RUNTIME_CONSTRAINTS = [
    "只输出研究、风险和拟单建议；不要尝试真实交易。",
    "不要请求或泄露 secret、环境变量、配置原文或本机路径。",
    "不要要求完整持仓、完整自选、完整历史、完整报告或工具台账明细。",
    "如果上下文不足，明确说明缺失并基于当前摘要推理。",
]


def build_prompt_envelope(
    *,
    user_message: str,
    skill_trace: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "envelope_version": "v0.21",
        "user_message": user_message,
        "current_page": context.get("page") or "overview",
        "skill_trace": _trim_skill_trace(skill_trace),
        "condensed_stock_context": _trim_stock_context(context),
        "condensed_page_context": _trim_page_context(context),
        "safety_constraints": SAFE_RUNTIME_CONSTRAINTS,
    }
    # RTO: downstream the planned skills' output schemas so structured output
    # stays consistent even when the SKILL.md body isn't injected this turn.
    plan_skills = [item.get("skill") for item in skill_trace if item.get("skill")]
    schemas = {s: skill_specs.output_schema(s) for s in plan_skills}
    schemas = {s: v for s, v in schemas.items() if v}
    if schemas:
        envelope["skill_output_schemas"] = schemas
    # Multi-agent synthesis: when both a research-leaning skill and risk-officer
    # are in the plan, ask the model to surface bull/bear tension and synthesize.
    if "risk-officer" in plan_skills and any(s in _RESEARCH_SKILLS for s in plan_skills):
        envelope["synthesis_directive"] = (
            "本轮涉及研究(看多侧)与风控(看空/约束侧)：请分别给出正方(bull)与反方(bear)论点，"
            "明确呈现二者张力，再给出权衡后的综合结论与不确定性。"
        )
    if context.get("turn_summary"):
        envelope["turn_summary"] = context["turn_summary"]
    if context.get("session_state"):
        envelope["session_state"] = context["session_state"]
    if context.get("previous_tool_calls"):
        envelope["previous_tool_calls"] = context["previous_tool_calls"]
    return envelope


def render_prompt_envelope(
    *,
    user_message: str,
    skill_trace: list[dict[str, Any]],
    context: dict[str, Any],
) -> str:
    envelope = build_prompt_envelope(user_message=user_message, skill_trace=skill_trace, context=context)
    # 紧凑序列化：发给 LLM 的 prompt 不需要缩进/空格，indent=2 会白白消耗 token。
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def _trim_skill_trace(skill_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed: list[dict[str, Any]] = []
    for item in skill_trace:
        record = {
            "step": item.get("step"),
            "skill": item.get("skill"),
            "purpose": item.get("purpose"),
            "authority_level": item.get("authority_level"),
            "status": item.get("status"),
        }
        tools = item.get("tools") or []
        if tools:
            record["tools"] = list(tools)[:4]
        if item.get("blocked_reason"):
            record["blocked_reason"] = item["blocked_reason"]
        trimmed.append(record)
    return trimmed


def _trim_stock_context(context: dict[str, Any]) -> dict[str, Any] | None:
    if "symbol_summary" in context and isinstance(context["symbol_summary"], dict):
        context = context["symbol_summary"]
    symbol = context.get("symbol")
    if not symbol:
        return None

    price = context.get("price") or {}
    relation = context.get("relation") or {}
    holding = context.get("holding") or {}
    ai_state = context.get("ai_state") or {}
    latest_report = context.get("latest_report") or {}

    return {
        "symbol": symbol,
        "name": context.get("name"),
        "market": context.get("market"),
        "industry": context.get("industry"),
        "sector": context.get("sector"),
        "price": {
            "last": price.get("last"),
            "change_pct": price.get("change_pct"),
            "updated_at": price.get("updated_at"),
            "source": price.get("source"),
            "degraded": price.get("degraded"),
        },
        "relation": {
            "in_watchlist": relation.get("in_watchlist"),
            "in_holdings": relation.get("in_holdings"),
            "monitored": relation.get("monitored"),
        },
        "holding_summary": {
            "weight_pct": holding.get("weight_pct"),
            "market_value": holding.get("market_value"),
            "pnl_pct": holding.get("pnl_pct"),
        },
        "ai_state": {
            "score": ai_state.get("score"),
            "risk_label": ai_state.get("risk_label"),
            "stance": ai_state.get("stance"),
            "confidence": ai_state.get("confidence"),
        },
        "latest_report_ref": {
            "report_id": latest_report.get("report_id"),
            "generated_at": latest_report.get("generated_at"),
        },
    }


def _trim_page_context(context: dict[str, Any]) -> dict[str, Any] | None:
    page_keys = {
        "overview", "holdings", "monitor", "reports", "tasks",
        "journal", "inbox", "active_risk_policy", "paper_portfolio",
    }
    page_context = {key: context[key] for key in page_keys if key in context and context[key] is not None}
    if not page_context:
        return None
    return _limit_value(page_context)


def _limit_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "<truncated>"
    if isinstance(value, dict):
        limited: dict[str, Any] = {}
        for key, item in list(value.items())[:10]:
            if key in {"markdown", "content", "full_content", "arguments", "token", "secret", "api_key"}:
                continue
            limited[key] = _limit_value(item, depth=depth + 1)
        return limited
    if isinstance(value, list):
        return [_limit_value(item, depth=depth + 1) for item in value[:5]]
    if isinstance(value, str) and len(value) > 280:
        return value[:279] + "…"
    return value

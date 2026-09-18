"""User investment risk appetite for opportunity-discovery prompts."""

from __future__ import annotations

from typing import Any

CONFIG_KEY = "investor_profile"

RISK_LEVELS = ("conservative", "moderate", "aggressive")

RISK_LEVEL_LABELS_ZH: dict[str, str] = {
    "conservative": "保守",
    "moderate": "普通",
    "aggressive": "激进",
}

DEFAULT_INVESTOR_PROFILE: dict[str, str] = {
    "risk_level": "moderate",
    "notes": "",
}

# Soft guidance injected into the discovery preamble (model judges; not a hard filter).
RISK_LEVEL_GUIDANCE_ZH: dict[str, str] = {
    "conservative": "偏防御与质量：大盘/龙头、低波动板块、蓝筹或高股息倾向；回避追涨停与小盘题材炒作。",
    "moderate": "板块轮动主线 + 中等弹性；机会与风险并重。",
    "aggressive": "可跟主题催化与高弹性、更小市值；仍须证据与来源，禁止编造。",
}


class InvestorProfileError(ValueError):
    """Invalid investor_profile payload."""


def normalize_investor_profile(raw: Any) -> dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    level = str(source.get("risk_level") or DEFAULT_INVESTOR_PROFILE["risk_level"]).strip().lower()
    if level not in RISK_LEVELS:
        raise InvestorProfileError(
            f"risk_level must be one of {', '.join(RISK_LEVELS)}; got {level!r}"
        )
    notes = str(source.get("notes") or "").strip()
    if len(notes) > 2000:
        notes = notes[:2000]
    return {"risk_level": level, "notes": notes}


def load_investor_profile(repo: Any) -> dict[str, str]:
    if repo is None:
        return dict(DEFAULT_INVESTOR_PROFILE)
    try:
        stored = repo.get_config(CONFIG_KEY, DEFAULT_INVESTOR_PROFILE)
    except Exception:
        stored = DEFAULT_INVESTOR_PROFILE
    try:
        return normalize_investor_profile(stored)
    except InvestorProfileError:
        return dict(DEFAULT_INVESTOR_PROFILE)


def format_profile_for_prompt(profile: dict[str, str] | None = None) -> str:
    """Chinese block for Copilot duty / discovery prompts."""
    p = profile or dict(DEFAULT_INVESTOR_PROFILE)
    try:
        p = normalize_investor_profile(p)
    except InvestorProfileError:
        p = dict(DEFAULT_INVESTOR_PROFILE)
    level = p["risk_level"]
    label = RISK_LEVEL_LABELS_ZH.get(level, level)
    guidance = RISK_LEVEL_GUIDANCE_ZH.get(level, "")
    lines = [
        f"用户理财风险承受等级：{label}（{level}）。",
        f"发现侧重点：{guidance}",
    ]
    notes = (p.get("notes") or "").strip()
    if notes:
        lines.append(f"用户自述（须优先尊重）：{notes}")
    else:
        lines.append("用户自述：无。")
    return "\n".join(lines)

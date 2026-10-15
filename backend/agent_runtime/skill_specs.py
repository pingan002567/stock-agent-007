"""Single source of truth for workbench investment skills.

SKILL.md (frontmatter + body) is THE source for description, allowed-tools, and
the subagent system prompt. This module only adds runtime-only fields that do
not belong in a SKILL.md (label, extra tools, turn/timeout limits, enabled/locked).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "custom"
_DEFAULT_DISALLOWED = ("task", "place_real_order")


def skill_md_path(name: str) -> Path:
    """Prefer the DeerFlow user-custom copy; repo ``skills/custom`` is only the seed."""
    installed = _installed_skill_md(name)
    if installed is not None and installed.is_file():
        return installed
    return _SKILLS_DIR / name / "SKILL.md"


def _installed_skill_md(name: str) -> Path | None:
    try:
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import DEFAULT_USER_ID
    except Exception:
        return None
    return get_paths().user_custom_skills_dir(DEFAULT_USER_ID) / name / "SKILL.md"


def _read_skill_md(name: str) -> tuple[str, list[str], str]:
    """Return (description, allowed_tools, markdown_body) from a skill's SKILL.md."""
    path = skill_md_path(name)
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    frontmatter = m.group(1) if m else ""
    body = (m.group(2) if m else text).strip()
    description = ""
    tools: list[str] = []
    in_tools = False
    for line in frontmatter.splitlines():
        if re.match(r"^description\s*:", line):
            description = line.split(":", 1)[1].strip()
            in_tools = False
        elif re.match(r"^allowed-tools\s*:", line):
            in_tools = True
        elif in_tools and re.match(r"^\s*-\s+", line):
            tools.append(line.split("-", 1)[1].strip())
        elif in_tools and not line.startswith((" ", "\t")):
            in_tools = False
    return description, tools, body


@dataclass(frozen=True)
class WorkbenchSkill:
    label: str
    authority: str = "A2"
    extra_tools: tuple[str, ...] = ("web_search",)
    disallowed_extra: tuple[str, ...] = ()
    max_turns: int = 30
    timeout_seconds: int = 300
    enabled: bool = True
    locked: bool = False
    is_subagent: bool = True
    synthetic_description: str = ""
    synthetic_tools: tuple[str, ...] = ()


WORKBENCH_SKILLS: dict[str, WorkbenchSkill] = {
    "stock-researcher": WorkbenchSkill(
        label="AI 研究员",
        authority="A2",
        max_turns=50,
        timeout_seconds=600,
    ),
    "valuation-analyst": WorkbenchSkill(
        label="AI 估值分析师",
        authority="A2",
        max_turns=40,
        timeout_seconds=600,
    ),
    "catalyst-tracker": WorkbenchSkill(
        label="AI 催化剂追踪",
        authority="A2",
        max_turns=30,
        timeout_seconds=300,
    ),
    "risk-officer": WorkbenchSkill(
        label="AI 风控官", authority="A3", max_turns=30, timeout_seconds=300,
    ),
    "strategy-analyst": WorkbenchSkill(
        label="AI 策略分析师", authority="A3", max_turns=30, timeout_seconds=600,
    ),
    "rebalance-planner": WorkbenchSkill(
        label="AI 调仓规划师", authority="A4", max_turns=40, timeout_seconds=600,
    ),
    "stock-monitor": WorkbenchSkill(
        label="AI 盯盘员", authority="A2", max_turns=20, timeout_seconds=300,
    ),
    "report-writer": WorkbenchSkill(
        label="AI 报告员", authority="A2", max_turns=20, timeout_seconds=300,
    ),
    "sector-rotation-report": WorkbenchSkill(
        label="AI 板块轮动报告",
        authority="A2",
        max_turns=40,
        timeout_seconds=600,
    ),
    "execution-agent-disabled": WorkbenchSkill(
        label="AI 执行代理",
        authority="A5",
        enabled=False,
        locked=True,
        is_subagent=False,
        synthetic_description="（已禁用）执行代理",
        synthetic_tools=("paper_trade",),
    ),
}


def subagent_config_dicts() -> dict[str, dict]:
    """DeerFlow ``subagents.custom_agents`` section, generated from SKILL.md."""
    out: dict[str, dict] = {}
    for name, spec in WORKBENCH_SKILLS.items():
        if not spec.is_subagent:
            continue
        description, allowed, body = _read_skill_md(name)
        tools = list(dict.fromkeys([*allowed, *spec.extra_tools]))
        out[name] = {
            "description": description,
            "system_prompt": body,
            "tools": tools,
            "disallowed_tools": [*_DEFAULT_DISALLOWED, *spec.disallowed_extra],
            "max_turns": spec.max_turns,
            "timeout_seconds": spec.timeout_seconds,
        }
    return out


def skill_registry_specs() -> dict[str, dict]:
    """Copilot skill registry rows (label/tools/enabled/locked)."""
    out: dict[str, dict] = {}
    for name, spec in WORKBENCH_SKILLS.items():
        if spec.is_subagent:
            _, allowed, _ = _read_skill_md(name)
            tools = list(dict.fromkeys([*allowed, *spec.extra_tools]))
        else:
            tools = list(spec.synthetic_tools)
        out[name] = {
            "label": spec.label,
            "tools": tools,
            "enabled": spec.enabled,
            "locked": spec.locked,
        }
    return out


def subagent_names() -> set[str]:
    return {name for name, spec in WORKBENCH_SKILLS.items() if spec.is_subagent and spec.enabled}


def skill_labels() -> dict[str, str]:
    return {name: spec.label for name, spec in WORKBENCH_SKILLS.items()}


def skill_authority() -> dict[str, str]:
    return {name: spec.authority for name, spec in WORKBENCH_SKILLS.items()}


def subagent_supported() -> bool:
    import os

    return os.getenv("WORKBENCH_AI_SUBAGENT", "").strip().lower() not in {"0", "false", "off"}


def plan_mode_supported() -> bool:
    import os

    return os.getenv("WORKBENCH_AI_PLAN_MODE", "").strip().lower() not in {"0", "false", "off"}

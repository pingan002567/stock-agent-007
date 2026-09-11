"""SKILL.md is the source of custom_agents; Copilot does not predeclare a skill_trace."""

from __future__ import annotations

from backend.agent_runtime import skill_specs
from backend.agent_runtime.skill_registry import SkillRegistry


def test_custom_agents_come_from_skill_md():
    agents = skill_specs.subagent_config_dicts()
    assert set(agents) == {
        "stock-researcher",
        "valuation-analyst",
        "catalyst-tracker",
        "risk-officer",
        "strategy-analyst",
        "rebalance-planner",
        "stock-monitor",
        "report-writer",
    }
    researcher = agents["stock-researcher"]
    assert "反方" in researcher["system_prompt"]
    assert "不要委派" in researcher["description"] or "不要委派" in researcher["system_prompt"]
    planner = agents["rebalance-planner"]
    assert "task(risk-officer)" in planner["system_prompt"]


def test_every_subagent_is_in_registry():
    known = set(SkillRegistry().skills)
    for name in skill_specs.subagent_names():
        assert name in known, f"unknown skill {name}"
    assert "execution-agent-disabled" in known
    assert SkillRegistry().skills["execution-agent-disabled"].locked is True

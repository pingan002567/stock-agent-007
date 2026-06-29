"""Guard: every intent's skill_trace must build for all skills in its plan.

Regression for the bug where adding a skill to INTENT_PLANS (valuation-analyst,
catalyst-tracker) without a matching _skill_purpose entry raised KeyError and
broke stock_research chat.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.agent_runtime import skill_specs
from backend.bootstrap import create_services
from backend.schemas import AuthorityLevel, CopilotRequest


def test_skill_trace_builds_for_every_intent():
    services = create_services(db_path=str(Path(tempfile.mkdtemp()) / "t.sqlite3"))
    copilot = services.copilot_service
    for intent in skill_specs.intent_plans():
        trace = copilot._build_skill_trace(
            intent, CopilotRequest(message="x", authority_level=AuthorityLevel.A4)
        )
        assert trace, f"empty skill_trace for intent {intent}"
        # every planned skill resolves to a purpose string (no KeyError)
        for step in trace:
            assert step.get("skill")
            assert step.get("purpose")


def test_every_plan_skill_is_in_registry():
    services = create_services(db_path=str(Path(tempfile.mkdtemp()) / "t.sqlite3"))
    known = set(services.copilot_service.skill_registry.skills)
    for intent, plan in skill_specs.intent_plans().items():
        for skill in plan:
            assert skill in known, f"{intent} plan references unknown skill {skill}"

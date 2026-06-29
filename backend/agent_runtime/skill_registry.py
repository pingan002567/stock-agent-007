from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from backend.agent_runtime import skill_specs

# Single source of truth: labels / intent-mapping / skill registry are generated
# from skill_specs (SKILL.md frontmatter + the WORKBENCH_SKILLS table).
SKILL_LABELS: Dict[str, str] = skill_specs.skill_labels()
INTENT_SKILLS: Dict[str, set[str]] = skill_specs.intent_skills()


@dataclass(frozen=True)
class SkillSpec:
    name: str
    label: str
    tools: List[str]
    enabled: bool = True
    locked: bool = False


DEFAULT_SKILLS: Dict[str, SkillSpec] = {
    name: SkillSpec(name, row["label"], list(row["tools"]), row["enabled"], row["locked"])
    for name, row in skill_specs.skill_registry_specs().items()
}


class SkillRegistry:
    def __init__(self, skills: Dict[str, SkillSpec] | None = None) -> None:
        self.skills = skills or DEFAULT_SKILLS

    def get(self, name: str) -> SkillSpec:
        if name not in self.skills:
            raise KeyError(name)
        skill = self.skills[name]
        if not skill.enabled:
            raise PermissionError(f"skill disabled: {name}")
        return skill

    def list(self) -> Iterable[SkillSpec]:
        return self.skills.values()

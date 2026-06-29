from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

SKILL_LABELS: Dict[str, str] = {
    "stock-researcher": "AI 研究员",
    "stock-monitor": "AI 盯盘员",
    "risk-officer": "AI 风控官",
    "strategy-analyst": "AI 策略分析师",
    "rebalance-planner": "AI 调仓规划师",
    "report-writer": "AI 报告员",
    "valuation-analyst": "AI 估值分析师",
}

INTENT_SKILLS: Dict[str, set[str]] = {
    "stock_research": {"stock-researcher", "valuation-analyst", "report-writer"},
    "strategy_backtest": {"strategy-analyst", "report-writer"},
    "rebalance_plan": {"stock-researcher", "risk-officer", "rebalance-planner", "report-writer"},
    "risk_review": {"risk-officer", "report-writer"},
    "monitor_event": {"stock-monitor", "report-writer"},
    "copilot_chat": {"stock-researcher", "report-writer"},
}


@dataclass(frozen=True)
class SkillSpec:
    name: str
    label: str
    tools: List[str]
    enabled: bool = True
    locked: bool = False


DEFAULT_SKILLS: Dict[str, SkillSpec] = {
    "stock-researcher": SkillSpec("stock-researcher", "AI 研究员", ["quote", "history", "intel", "report", "web_search"]),
    "stock-monitor": SkillSpec("stock-monitor", "AI 盯盘员", ["quote", "intel", "monitor_event", "web_search"]),
    "risk-officer": SkillSpec("risk-officer", "AI 风控官", ["portfolio", "risk", "audit", "review_inbox", "web_search"]),
    "strategy-analyst": SkillSpec(
        "strategy-analyst", "AI 策略分析师",
        ["list_strategies", "run_strategy_backtest", "get_backtest_result", "history", "quote", "web_search"],
    ),
    "rebalance-planner": SkillSpec("rebalance-planner", "AI 调仓规划师", ["portfolio", "risk", "draft_order", "web_search"]),
    "report-writer": SkillSpec("report-writer", "AI 报告员", ["report", "history", "audit", "web_search"]),
    "valuation-analyst": SkillSpec("valuation-analyst", "AI 估值分析师", ["get_stock_financial", "get_stock_context", "history", "web_search"]),
    "execution-agent-disabled": SkillSpec("execution-agent-disabled", "AI 执行代理", ["paper_trade"], enabled=False, locked=True),
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

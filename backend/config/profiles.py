"""智能体配置档：一组「模型 + 技能」的预设。

名字用**能力档**，不用职称：「个股研判档」而不是「AI 研究员」。
职称只出现在 SKILL.md 正文的角色段落里（见 doc/SKILL_SYSTEM.md §2.5）。
"""

DEFAULT_PROFILES = [
    {
        "name": "Copilot",
        "default_model": "gpt-5.4",
        "purpose": "右侧全局对话与任务指挥",
        "skills": ["stock-deep-dive", "watch-rule-monitor", "portfolio-risk-audit", "rebalance-plan"],
    },
    {
        "name": "个股研判档",
        "default_model": "claude-sonnet-4.6",
        "purpose": "单股深研、报告、追问",
        "skills": ["stock-deep-dive", "report-render"],
    },
    {
        "name": "盯盘巡检档",
        "default_model": "gpt-5.4",
        "purpose": "事件解释、盯盘策略控制",
        "skills": ["watch-rule-monitor", "portfolio-risk-audit"],
    },
    {
        "name": "风险审阅档",
        "default_model": "gpt-5.4",
        "purpose": "组合风险、规则检查、仓位边界",
        "skills": ["portfolio-risk-audit"],
    },
    {
        "name": "调仓规划档",
        "default_model": "gpt-5.4",
        "purpose": "方案模拟与拟单草案",
        "skills": ["rebalance-plan"],
    },
]

#: 旧职称 → 能力档。老安装里 profiles 已经把旧名存进配置了，
#: 只改默认值不会生效，读取时按这张表就地改名（其它字段不动）。
LEGACY_PROFILE_NAMES = {
    "AI 研究员": "个股研判档",
    "AI 盯盘员": "盯盘巡检档",
    "AI 风控官": "风险审阅档",
    "AI 调仓规划师": "调仓规划档",
}


def normalize_profile_names(items: list[dict]) -> list[dict]:
    """把存量配置里的旧职称名换成能力档名（幂等）。"""
    out = []
    for item in items or []:
        name = str((item or {}).get("name") or "")
        mapped = LEGACY_PROFILE_NAMES.get(name)
        out.append({**item, "name": mapped} if mapped else item)
    return out

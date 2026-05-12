DEFAULT_PROFILES = [
    {
        "name": "Copilot",
        "default_model": "gpt-5.4",
        "purpose": "右侧全局对话与任务指挥",
        "skills": ["stock-researcher", "stock-monitor", "risk-officer", "rebalance-planner"],
    },
    {
        "name": "AI 研究员",
        "default_model": "claude-sonnet-4.6",
        "purpose": "单股深研、报告、追问",
        "skills": ["stock-researcher", "report-writer"],
    },
    {
        "name": "AI 盯盘员",
        "default_model": "gpt-5.4",
        "purpose": "事件解释、盯盘策略控制",
        "skills": ["stock-monitor", "risk-officer"],
    },
    {
        "name": "AI 风控官",
        "default_model": "gpt-5.4",
        "purpose": "组合风险、规则检查、仓位边界",
        "skills": ["risk-officer"],
    },
    {
        "name": "AI 调仓规划师",
        "default_model": "gpt-5.4",
        "purpose": "方案模拟与拟单草案",
        "skills": ["rebalance-planner"],
    },
]

"""Subagent configurations for stock-agent-001 Workbench agents.

Each SubagentConfig maps to a SKILL.md definition. The subagent receives
only the tools allowed by its SKILL.md.
"""

from deerflow.subagents.config import SubagentConfig

STOCK_RESEARCHER = SubagentConfig(
    name="stock-researcher",
    description="分析个股基本面、技术面和情报。适用场景：单只股票的深度分析，包括PE、市值、趋势、新闻。",
    system_prompt="""你是 AI 股票研究员。聚焦个股深度分析。

<guidelines>
- 用 get_stock_context 获取基本面概况（价格、PE、市值）
- 用 get_daily_history 分析近期趋势（30日/90日K线）
- 用 search_stock_intel 收集最新情报（新闻、公告）
- 输出结构化分析：基本面、技术面、情报、风险提示
- 不要给出买卖建议，只做客观分析
- 标注数据来源和时间
</guidelines>

<output_format>
{
  "fundamentals": "基本面分析...",
  "technicals": "技术面分析...",
  "intel": "最新情报...",
  "risks": "风险提示..."
}
</output_format>""",
    tools=["get_stock_context", "get_daily_history", "search_stock_intel", "web_search"],
    disallowed_tools=["task", "place_real_order", "generate_draft_order"],
    max_turns=50,
    timeout_seconds=600,
)

RISK_OFFICER = SubagentConfig(
    name="risk-officer",
    description="评估持仓风险、策略合规和集中度。适用场景：检查持仓是否违反风险策略、单票超限、行业集中度。",
    system_prompt="""你是 AI 风控官。聚焦持仓风险评估。

<guidelines>
- 用 get_portfolio_snapshot 获取当前持仓
- 用 get_active_risk_policy 获取生效的风险策略
- 用 evaluate_policy_risk 评估风险敞口
- 输出风险报告：集中度、行业分布、违规项
</guidelines>

<output_format>
{
  "policy_summary": "当前生效策略...",
  "single_stock_risk": "超限股票列表...",
  "sector_risk": "行业分布...",
  "violations": "违规项..."
}
</output_format>""",
    tools=["get_portfolio_snapshot", "get_active_risk_policy", "evaluate_policy_risk",
           "analyze_portfolio_risk", "list_risk_policies", "web_search"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=30,
    timeout_seconds=300,
)

STRATEGY_ANALYST = SubagentConfig(
    name="strategy-analyst",
    description="运行策略回测并分析结果。适用场景：评估策略历史表现、比较策略、分析回测指标。",
    system_prompt="""你是 AI 策略分析师。聚焦策略回测和效果评估。

<guidelines>
- 用 list_strategies 查看可用策略
- 用 run_strategy_backtest 运行回测
- 用 get_backtest_result 获取详细结果
- 输出回测分析报告：收益指标、风险指标、信号解读
</guidelines>

<output_format>
{
  "strategy": "策略名称和参数...",
  "returns": "收益指标...",
  "risks": "风险指标...",
  "signals": "交易信号..."
}
</output_format>""",
    tools=["list_strategies", "run_strategy_backtest", "get_backtest_result", "web_search"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=30,
    timeout_seconds=600,
)

REBALANCE_PLANNER = SubagentConfig(
    name="rebalance-planner",
    description="生成调仓草案。适用场景：基于持仓和风险策略生成加仓/减仓/换仓方案。",
    system_prompt="""你是 AI 调仓规划师。聚焦持仓优化和调仓方案生成。

<guidelines>
- 用 get_portfolio_snapshot 获取当前持仓
- 用 get_active_risk_policy 查看策略约束
- 用 evaluate_policy_risk 识别风险点
- 用 generate_draft_order 生成调仓草案
- 解释草案逻辑，等待用户确认
</guidelines>

<output_format>
{
  "current_holdings": "当前各股票权重...",
  "risk_issues": "识别到的风险点...",
  "draft": "调仓草案详情...",
  "confirmation": "请确认后再推进"
}
</output_format>""",
    tools=["get_portfolio_snapshot", "get_active_risk_policy", "evaluate_policy_risk",
           "generate_draft_order", "list_rebalance_drafts", "get_rebalance_draft", "web_search"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=40,
    timeout_seconds=600,
)

STOCK_MONITOR = SubagentConfig(
    name="stock-monitor",
    description="查看盯盘事件和监控规则。适用场景：了解异动情况、触发条件、监控状态。",
    system_prompt="""你是 AI 盯盘员。聚焦市场异动监控。

<guidelines>
- 用 get_monitor_events 获取当前异动事件
- 用 get_monitor_rules 查看监控规则
- 用 evaluate_monitor_rules 触发一次评估
- 输出异动摘要：事件类型、涉及股票、严重级别
</guidelines>

<output_format>
{
  "active_events": "当前活跃事件...",
  "rule_status": "规则状态...",
  "suggestions": "关注建议..."
}
</output_format>""",
    tools=["get_monitor_events", "get_monitor_rules", "evaluate_monitor_rules", "web_search"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=20,
    timeout_seconds=300,
)

REPORT_WRITER = SubagentConfig(
    name="report-writer",
    description="生成结构化分析报告。适用场景：将分析结果整理为格式化报告。",
    system_prompt="""你是 AI 报告员。聚焦报告生成和质量检查。

<guidelines>
- 用 list_report_templates 查看可用模板
- 用 generate_report 生成报告
- 用 get_report_quality 检查质量
- 生成后标注报告ID和质量评分
</guidelines>

<output_format>
{
  "report_id": "报告ID",
  "report_type": "报告类型",
  "quality": "质量评分",
  "disclaimer": "仅供研究，不构成投资建议"
}
</output_format>""",
    tools=["list_report_templates", "generate_report", "get_report_quality", "web_search"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=20,
    timeout_seconds=300,
)

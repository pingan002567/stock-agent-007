# Chat 多 Agent 管理方案

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 1. 现状：声明式 Skill Trace（非真正多 Agent）

当前的多 Agent 是一个**声明式标签系统**，不涉及真正的多 Agent 执行：

```
用户消息 → IntentRouter → SkillRegistry → 产出 Skill Trace
                                   │
        ┌──────────────────────────┘
        │  plan: stock_research → [stock-researcher, report-writer]
        │  但这些 skill 只是元数据标签，实际执行只有 1 个 lead agent
        ▼
   Lead Agent（唯一执行者）
   拥有全部 38 个工具，同时扮演"研究员 + 报告员"
```

`SkillRegistry` 定义的 6 个 skill 是**文档概念**，不是运行时对象：

```python
# 当前只是元数据
"stock-researcher":  SkillSpec("stock-researcher", "AI 研究员", ["quote", "history", "intel"])
"risk-officer":      SkillSpec("risk-officer", "AI 风控官", ["portfolio", "risk", "audit"])
# ...它们不会真的分离执行
```

---

## 2. DeerFlow 的真正多 Agent：Subagent 系统

DeerFlow 有一个完整的子智能体系统（当前项目 `subagent_enabled=False`）：

```
Lead Agent 调用 task() 工具
│
├── task(subagent_type="general-purpose", description="分析AAPL基本面", prompt="...")
│
├── SubagentLimitMiddleware → 限流（最多3并发）
│
└── SubagentExecutor（ThreadPoolExecutor）
    │
    ├── Subagent 1: 独立上下文、工具子集、system_prompt
    ├── Subagent 2: 独立上下文、工具子集、system_prompt
    └── Subagent 3: 独立上下文、工具子集、system_prompt
         │
         └── 各自完成后返回结构化结果 → Lead Agent 整合
```

每个 Subagent 有独立配置：

```python
SubagentConfig(
    name="stock-researcher",         # 名称
    description="分析个股基本面...",   # Lead Agent 看到的使用说明
    system_prompt="你是股票研究员...", # 角色提示词
    tools=["get_stock_context",      # 工具白名单（仅 A2 工具）
           "get_daily_history",
           "search_stock_intel"],
    disallowed_tools=["task"],       # 禁止嵌套
    model="inherit",                 # 继承 Lead Agent 的模型
    max_turns=50,                    # 最多 50 轮
    timeout_seconds=600,             # 10 分钟超时
)
```

---

## 3. 推荐方案：三层多 Agent 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: CopilotService（编排层）                            │
│                                                              │
│  intent_router → skill_plan                                  │
│                                                              │
│  简单 intent (stock_research):                                │
│    → Lead Agent 直接处理（无 Subagent）                        │
│                                                              │
│  复杂 intent (rebalance_plan):                                │
│    → 启用 subagent_enabled=True                               │
│    → Lead Agent 收到 skill plan 后用 task() 调度 Subagent     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Lead Agent（协调层）                                │
│                                                              │
│  收到: "全面评估 AAPL 并生成调仓建议"                           │
│                                                              │
│  调用 task("stock-researcher", "分析 AAPL 基本面和技术面")      │
│  调用 task("risk-officer", "评估当前持仓风险")                 │
│  调用 task("strategy-analyst", "运行回测")  ← 如果有           │
│                                                              │
│  等待 3 个 Subagent 完成 → 汇总 → 调用 report-writer 生成报告   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Subagents（执行层）                                 │
│                                                              │
│  Subagent "stock-researcher":                                │
│    工具: get_stock_context, get_daily_history, search_intel   │
│    system_prompt: "你是股票研究员，聚焦基本面分析..."            │
│    → 返回结构化结果 {基本面:..., 技术面:..., 风险:...}          │
│                                                              │
│  Subagent "risk-officer":                                    │
│    工具: get_portfolio_snapshot, evaluate_policy_risk          │
│    system_prompt: "你是风控官，聚焦风险指标..."                  │
│    → 返回 {集中度:..., 行业风险:..., 建议:...}                  │
│                                                              │
│  Subagent "strategy-analyst":                                │
│    工具: run_strategy_backtest                                │
│    → 返回 {回测结果:..., 信号:...}                             │
└─────────────────────────────────────────────────────────────┘
```

### 实现步骤

#### Step 1: 为每个 Skill 定义 SubagentConfig

```python
# backend/agent_runtime/subagent_configs.py

from deerflow.subagents.config import SubagentConfig

STOCK_RESEARCHER = SubagentConfig(
    name="stock-researcher",
    description="分析个股基本面、技术面和情报。适用场景：需要深入了解单只股票的估值、趋势和新闻。",
    system_prompt="""你是 AI 股票研究员。你的工作是深度分析指定股票。

<guidelines>
- 先用 get_stock_context 获取基本面概况
- 用 get_daily_history 分析近期趋势
- 用 search_stock_intel 收集最新情报
- 输出结构化分析：基本面、技术面、情报、风险
- 不要给出买卖建议，只做客观分析
</guidelines>

<output_format>
{
  "fundamentals": "基本面分析...",
  "technicals": "技术面分析...",
  "intel": "最新情报...",
  "risks": "风险提示..."
}
</output_format>""",
    tools=["get_stock_context", "get_daily_history", "search_stock_intel"],
    disallowed_tools=["task", "place_real_order", "generate_draft_order"],
    max_turns=50,
    timeout_seconds=600,
)

RISK_OFFICER = SubagentConfig(
    name="risk-officer",
    description="评估持仓风险、策略合规和集中度。适用场景：需要检查持仓是否违反风险策略。",
    system_prompt="""你是 AI 风控官。你的工作是评估持仓风险。

<guidelines>
- 用 get_portfolio_snapshot 获取当前持仓
- 用 get_active_risk_policy 获取生效的风险策略
- 用 evaluate_policy_risk 评估风险敞口
- 输出风险报告：集中度、行业分布、违规项
</guidelines>""",
    tools=["get_portfolio_snapshot", "get_active_risk_policy", "evaluate_policy_risk",
           "list_risk_policies", "analyze_portfolio_risk"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=30,
    timeout_seconds=300,
)

STRATEGY_ANALYST = SubagentConfig(
    name="strategy-analyst",
    description="运行策略回测并分析结果。适用场景：需要评估策略的历史表现。",
    system_prompt="""你是 AI 策略分析师。你的工作是运行和解读策略回测。

<guidelines>
- 用 list_strategies 查看可用策略
- 用 run_strategy_backtest 运行回测
- 用 get_backtest_result 获取详细结果
- 输出：策略表现、收益指标、风险指标、信号解读
</guidelines>""",
    tools=["list_strategies", "run_strategy_backtest", "get_backtest_result"],
    disallowed_tools=["task", "place_real_order"],
    max_turns=30,
    timeout_seconds=600,
)
```

#### Step 2: 在 deerflow_config.py 注册 Subagent

```python
# deerflow_config.py
from backend.agent_runtime.subagent_configs import (
    STOCK_RESEARCHER, RISK_OFFICER, STRATEGY_ANALYST,
)

config = {
    "models": [...],
    "tools": [...],
    "subagents": {
        "timeout_seconds": 900,
        "custom_agents": {
            "stock-researcher": {
                "description": STOCK_RESEARCHER.description,
                "system_prompt": STOCK_RESEARCHER.system_prompt,
                "tools": STOCK_RESEARCHER.tools,
                "disallowed_tools": STOCK_RESEARCHER.disallowed_tools,
                "max_turns": STOCK_RESEARCHER.max_turns,
                "timeout_seconds": STOCK_RESEARCHER.timeout_seconds,
            },
            "risk-officer": { ... },
            "strategy-analyst": { ... },
        },
    },
}
```

#### Step 3: 按 intent 动态启用 Subagent

```python
# copilot_service.py — stream_run() 中

# 复杂 intent 启用 subagent
COMPLEX_INTENTS = {"rebalance_plan", "strategy_backtest", "pre_trade_review"}

if state.intent in COMPLEX_INTENTS:
    client = DeerFlowClient(..., subagent_enabled=True)
else:
    client = DeerFlowClient(..., subagent_enabled=False)
```

---

## 4. 两种模式对比

| 维度 | 当前（Lead Agent 单打） | Subagent 模式 |
|------|------------------------|---------------|
| 执行方式 | 1 个 Agent 串行 | Lead + 最多 3 Subagent 并行 |
| 工具范围 | 38 个工具全可见 | 每个 Subagent 只看到自己的工具子集 |
| 上下文 | 共享，容易混淆角色 | 独立隔离，聚焦职责 |
| 适用场景 | 简单查询、单维度分析 | 多维度分析、复杂报告生成 |
| Token 消耗 | 全量工具 schema + 全量上下文 | 每个 Subagent 只加载子集 |
| 错误隔离 | 工具失败影响全局 | 一个 Subagent 失败不影响其他 |

---

## 5. Subagent 的安全边界

```
Subagent 的 tool whitelist 是第一道防线
  └── 只暴露 A2/A3 工具，A4/A5 不白名单

tool_bridge._handlers 是第二道防线
  └── ExecutionPolicy + PermissionGuard 仍然生效

place_real_order 永远是 blocked
  └── 即使 Subagent 尝试调用，tool 函数内部也会拒绝
```

### Subagent 工具白名单示例

```python
# stock-researcher: 只给 A2 研究工具
tools=["get_stock_context", "get_daily_history", "search_stock_intel"]

# risk-officer: 只给 A3 风险工具
tools=["get_portfolio_snapshot", "get_active_risk_policy", "evaluate_policy_risk"]

# 注意: generate_draft_order(A4) 和 place_real_order(A5) 永远不进白名单
```

---

## 6. 前端展示

Subagent 执行过程通过 SSE 事件可见：

```
SSE 事件流:
  skill_trace    → [{step:1, skill:"stock-researcher"}, {step:2, skill:"report-writer"}]
  tool_call      → {tool:"task", arguments:{subagent_type:"stock-researcher", ...}}
  reasoning      → {phase:"subagent_started", agent:"stock-researcher"}
  tool_result    → {tool:"task", result:"{基本面:..., 技术面:...}"}  ← Subagent 返回
  partial_answer → "根据各研究员的分析，综合建议如下..."
  final          → {conclusion:..., evidence_refs:[...]}
```

前端可以展示 Subagent 执行卡片：Agent 名称 + 耗时 + token 消耗 + 返回摘要。

---

## 7. 渐进式启用路线

```
Phase 1（当前）: subagent_enabled=False，Lead Agent 单打
    ↓
Phase 2: 为 "strategy_backtest" intent 启用 Subagent
    → 只有 strategy-analyst 一个 Subagent，风险可控
    ↓
Phase 3: 为 "rebalance_plan" intent 启用多 Subagent
    → stock-researcher + risk-officer + rebalance-planner 并行
    ↓
Phase 4: 所有复杂 intent 启用 Subagent + 结果缓存
    → 同一天内同一股票的 research 结果可复用
```

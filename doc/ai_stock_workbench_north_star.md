# 完全 AI 驱动股票工作台北极星设计

## 产品愿景

未来目标不是做一个“能聊股票的助手”，而是建设一个用户可以指挥 AI 做任何股票相关事情的工作台：

```text
用户目标
  -> AI 理解意图
  -> 自动选择 Skill
  -> 查询基础信息和证据
  -> 生成可执行计划或报告
  -> 需要时进入人工确认
  -> 任务、报告、审计沉淀
```

用户可以说：

- “帮我分析 AAPL 的持仓风险。”
- “盯住腾讯，如果政策消息恶化就提醒我。”
- “把组合波动降下来，给我一个调仓方案。”
- “生成白酒板块周度复盘。”
- “比较 AAPL、腾讯、茅台，告诉我哪个更值得加入自选。”

## AI 职责分工

AI 角色在产品层表现为 Skills，而不是固定 tab。它们应根据上下文自动被调度，也可以被用户显式指定。

| Skill | 中文角色 | 职责 | 当前权限 |
| --- | --- | --- | --- |
| `stock-researcher` | AI 研究员 | 单股深研、报告、追问、证据整理 | 开启 |
| `stock-monitor` | AI 盯盘员 | 控制盯盘策略、开关、事件解释 | 开启 |
| `risk-officer` | AI 风控官 | 组合风险、仓位规则、集中度诊断 | 开启 |
| `rebalance-planner` | AI 调仓规划师 | 调仓方案、拟单草案、影响模拟 | 开启但需确认 |
| `execution-agent-disabled` | AI 执行代理 | 未来真实执行接口 | V1 关闭 |

## Skill Trace 与 Team 边界

V1 中，Copilot 可以返回 `skill_trace`，用于说明本次请求经过了哪些 Skills、handoff 和权限边界。`skill_trace` 是声明式解释，不代表系统在产品运行时启动了一个独立多 Agent Team。

明确边界：

- 产品运行时不提供 Team Run 功能，不新增 `/api/team-runs`。
- 不新增独立 `TeamRuntime`、`TeamOrchestrator`、`team_run` 或 `agent_step` 存储。
- 多 agent 协作可以作为研发交付流程使用，例如 Architect / Developer / QA / Reviewer，但不作为用户可见的运行时对象。
- 未来接入 DeerFlow 真 runtime 时，应替换 `DeerFlowClientAdapter` 内部实现，而不是绕开 Copilot + Skill + SSE 边界另造编排层。

## AI 行为等级

AI 能力应按风险分级，不应一步跳到自动调仓。

| 等级 | 能力 | 示例 | 是否需要确认 |
| --- | --- | --- | --- |
| A1 | 查询与总结 | “解释今天市场变化” | 否 |
| A2 | 研究与报告 | “生成 AAPL 深研报告” | 否 |
| A3 | 风险诊断 | “扫描持仓集中度风险” | 否 |
| A4 | 拟单与调仓草案 | “建议减仓 AAPL 到 8%” | 是 |
| A5 | 真实交易执行 | “下单卖出 20 股” | V1 禁止 |

## 输出标准

所有 AI 结论必须包含：

- 结论。
- 证据引用。
- 置信度。
- 反对理由。
- 有效期。
- 数据源和更新时间。
- 权限等级。
- 风险提示。

调仓类输出还必须包含：

- 当前仓位。
- 目标仓位。
- 拟单草案。
- 组合影响。
- 触发条件。
- 人工确认状态。

## 工作流示例

### 单股深研

```text
用户输入“分析 AAPL 是否还能持有”
  -> IntentRouter 识别为 stock_research
  -> ContextBuilder 构造 StockContext
  -> AI 研究员调用行情、历史、情报、报告工具
  -> ResultNormalizer 校验输出
  -> ReportService 保存报告
  -> AuditService 记录深研任务
```

### AI 盯盘

```text
用户设置“腾讯政策风险升高时提醒”
  -> AI 盯盘员生成规则
  -> Monitor 模块持续收集行情/消息/事件
  -> 事件触发后生成 EventContext
  -> Copilot 解释原因和影响
  -> 用户可转入个股深研或持仓复核
```

### 调仓规划

```text
用户输入“把 AAPL 从 18% 降到 10%”
  -> AI 调仓规划师读取持仓和风险
  -> 生成 DecisionContext
  -> 输出拟单草案和组合影响
  -> 输出 execution_guard.auto_trade=false
  -> 进入人工确认
  -> V1 不连接真实交易
```

## 长期演进

1. V1：研究、盯盘、风控、调仓草案。
2. V2：更丰富的策略、回测、报告模板和个性化风险偏好。
3. V3：接入真实券商前的 paper trading 和交易前审查。
4. V4：在满足合规和治理要求后，探索受控执行能力。

核心原则：AI 可以主动，但必须可解释、可追踪、可拒绝、可回滚。

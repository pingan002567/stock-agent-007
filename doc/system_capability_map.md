# 系统能力关联图

## 一句话总结

用户围绕“自选、持仓、个股”工作，市场提供解释语境，盯盘负责持续发现变化，AI Skills 负责推理和行动建议，任务、报告、审计负责过程可见与结果沉淀。

## 页面能力关系

```text
总览
  ├─ 汇总：自选摘要 / 持仓摘要 / 个股焦点 / 市场状态 / 盯盘事件 / 待办
  ├─ 跳转：自选 / 持仓 / 个股 / 市场 / 盯盘 / 任务 / 报告
  ↓
自选 -> 个股 -> 深研报告 -> 报告库
持仓 -> 风险扫描 -> 调仓规划 -> 拟单草案 -> 交易前审查 -> 用户显式 paper order -> Paper Sandbox -> 审计
持仓 -> Paper Portfolio projection / snapshot / performance -> 复盘报告 -> Decision Journal -> Review Inbox overlay
市场 -> 板块 -> 关联标的 -> 个股 / 自选
盯盘 -> 事件 -> 个股复核 / 持仓复核 / Copilot 解释
策略 -> 回测 -> 候选操作 -> 调仓规划
Copilot -> Session / ContextCard -> IntentRouter -> Skill -> WorkbenchToolBridge -> Task -> Report / Audit
```

## 核心业务对象

| 对象 | 说明 | 主要页面 |
| --- | --- | --- |
| `watchlist_item` | 自选标的 | 自选、总览、个股 |
| `holding_position` | 持仓 | 持仓、总览、个股 |
| `rebalance_draft` | 持久化拟单草案 | 持仓、总览、Copilot、审计 |
| `pre_trade_review` | 交易前审查台账 | 持仓、Copilot、审计 |
| `paper_order` | 本地 paper sandbox 台账 | 持仓、设置、审计 |
| `paper_portfolio_snapshot` | append-only paper portfolio 快照 | 持仓、报告、审计 |
| `review_inbox_state` | Human Review Inbox overlay 状态 | 总览、Copilot、审计 |
| `stock_snapshot` | 个股快照 | 个股、总览 |
| `monitor_rule` | 持久化盯盘规则 | 盯盘、总览、Copilot |
| `monitor_status` | 盯盘运行状态 | 盯盘、总览 |
| `monitor_event` | 盯盘事件 | 盯盘、总览、个股、持仓 |
| `strategy_spec` | 持久化策略定义 | 策略、Copilot |
| `backtest_run` | append-only 回测结果 | 策略、任务回放、Copilot |
| `report_template` | code-first 报告模板可见性快照 | 报告、设置 |
| `agent_task` | AI 任务 | 任务、Copilot |
| `tool_execution` | 工具执行台账 | 任务、Copilot 回放 |
| `copilot_session` | AI Chat 会话 | 右侧 Chat、任务、审计 |
| `copilot_message` | AI Chat 持久化消息和 SSE 摘要 | 右侧 Chat、任务、审计 |
| `report` | 结果沉淀 | 报告、个股 |
| `report_quality_check` | append-only 报告质检记录 | 报告、Copilot |
| `audit_log` | 高风险和关键动作记录 | 任务、报告、设置 |
| `provider_config` | AI provider 配置 | 设置 |
| `model_config` | 模型配置 | 设置 |
| `skill_config` | Skill 开关、权限和工具范围 | 设置 |

## Context 类型

### StockContext

用于所有个股相关操作：

```yaml
StockContext:
  symbol
  name
  market
  industry
  sector
  price
  relation:
    in_watchlist
    in_holdings
    monitored
  holding
  ai_state
  latest_report
```

### EventContext

用于盯盘和事件解释：

```yaml
EventContext:
  event_id
  rule_id
  rule_type
  source
  symbol
  title
  severity
  trigger_rule
  dedupe_key
  cooldown_until
  evidence
  suggested_actions
```

### DecisionContext

用于高风险 AI 决策、调仓和拟单草案：

```yaml
DecisionContext:
  decision_id
  subject
  draft_id
  skill
  conclusion
  confidence
  reasons
  counter_reasons
  evidence_refs
  valid_until
  authority_level
  output
```

## AI Skills 和页面关系

| Skill | 主要入口 | 输入 | 输出 |
| --- | --- | --- | --- |
| AI 研究员 | 个股、Copilot、自选 | StockContext、问题、证据需求 | 深研结论、报告、追问 |
| AI 盯盘员 | 盯盘、总览、Copilot | 盯盘规则、行情、消息、持仓 | EventContext、提醒、规则建议 |
| AI 风控官 | 持仓、总览、Copilot | 持仓、风险规则、市场状态 | 风险诊断、限制建议 |
| AI 策略分析师 | 策略、Copilot | StrategySpec、历史行情、quotes、backtest history | 回测结果、候选动作、研究边界 |
| AI 调仓规划师 | 持仓、总览、Copilot | 风险结果、目标仓位、约束 | 调仓方案、拟单草案、交易前审查 |
| AI 执行代理 | 设置 | 拟单、授权、券商接口 | V1 关闭 |

## AI Chat Final Layer

v0.20 中 AI Chat 是统一指挥入口，但不是 TeamRun：

- 会话层：`copilot_session` 保存标题、当前页面、锚定股票和权限，`copilot_message` 保存用户消息、Skill Trace、工具调用摘要和 final answer。
- 恢复层：右侧 Chat 可以仅依赖持久化 `copilot_message + agent_task` 重建当前对话、工具过程卡和结果卡。
- 上下文层：`CopilotContextBuilder` 按页面注入精简上下文，避免把 secret、完整持仓、完整历史、完整报告或完整工具 ledger 放进会话。
- 工具层：低风险工具可由 Chat 自动执行并写 `tool_execution/audit`；草案确认、paper order、journal close、inbox done 必须由页面显式按钮触发。
- 安全层：`place_real_order`、TeamRun、`create_paper_order` ToolBridge 继续不存在或 blocked。

## Embedded Prompt Envelope

DeerFlow embedded 模式只接收精简 envelope，而不是整包 runtime context：

```yaml
PromptEnvelope:
  envelope_version
  user_message
  skill_trace:
    - step
    - skill
    - purpose
    - authority_level
    - status
    - tools
  condensed_stock_context:
    symbol
    name
    market
    industry
    sector
    price
    relation
    holding_summary
    ai_state
    latest_report_ref
  safety_constraints
```

禁止透传：

- secret / env
- full holdings / full watchlist
- full history / full report
- tool ledger detail

## Workbench Tool Bridge

Tool Bridge 是 AI Skills 调用系统能力的统一工具边界。它不改变页面信息架构，也不是新的 TeamRun runtime；它只把 Copilot/DeerFlow adapter 里的 `tool_call` 映射到本项目自有能力。

| 工具 | 权限 | 主要能力 | 输出去向 |
| --- | --- | --- | --- |
| `get_stock_context` | A2 | 个股上下文、持仓/自选关系、AI 状态 | 个股、Copilot、报告 |
| `get_daily_history` | A2 | 历史走势 | 个股图表、研究证据 |
| `search_stock_intel` | A2 | 新闻、公告、证据列表 | 个股证据、报告 |
| `get_portfolio_snapshot` | A3 | 持仓摘要 | 持仓、风控 |
| `get_active_risk_policy` | A2 | 读取当前 active/default 风险策略 | 设置、持仓、盯盘 |
| `list_risk_policies` | A2 | 读取风险策略列表 | 设置、Copilot |
| `evaluate_policy_risk` | A3 | 按 active policy 执行组合风险扫描 | 风控、调仓规划 |
| `analyze_portfolio_risk` | A3 | 兼容旧工具名，内部转发到 policy-aware 风险扫描 | 风控、调仓规划 |
| `get_monitor_events` | A2 | 盯盘事件读取与最新解释 | 盯盘、Copilot |
| `get_monitor_rules` | A2 | 盯盘规则读取 | 盯盘、设置 |
| `evaluate_monitor_rules` | A2 | 手动规则评估、写持久事件 | 盯盘、Copilot |
| `list_strategies` | A2 | 读取策略库 | 策略、Copilot |
| `run_strategy_backtest` | A3 | 执行只读回测并写 ledger | 策略、Copilot、任务 |
| `get_backtest_result` | A2 | 读取回测历史与 strategy snapshot | 策略、Copilot、任务回放 |
| `list_report_templates` | A2 | 读取报告模板注册表 | 报告、设置、Copilot |
| `generate_report` | A2 | 基于已有 source 生成报告与质量检查 | 报告、Copilot、任务 |
| `get_report_quality` | A2 | 读取报告质检历史与 latest summary | 报告、Copilot |
| `generate_draft_order` | A4 | 创建持久化拟单草案，`auto_trade=false` | 持仓、审计、Copilot |
| `list_rebalance_drafts` | A4 | 读取拟单草案列表 | 持仓、总览、Copilot |
| `get_rebalance_draft` | A4 | 读取单条拟单草案详情 | 持仓、总览、Copilot |
| `create_pre_trade_review` | A4 | 基于显式 confirmed `draft_id` 创建交易前审查，不创建 paper order | 持仓、Copilot、审计 |
| `list_pre_trade_reviews` | A3 | 读取交易前审查列表 | 持仓、Copilot |
| `list_paper_orders` | A3 | 读取本地 paper sandbox 台账 | 持仓、设置、Copilot |
| `get_paper_portfolio` | A3 | 读取 paper portfolio projection/read-model | 持仓、Copilot |
| `analyze_paper_performance` | A3 | 读取 since-baseline 绩效归因和最近 snapshot delta | 持仓、Copilot |
| `create_paper_portfolio_snapshot` | A3 | append-only snapshot，并写 audit/ledger | 持仓、报告、Copilot |
| `list_review_inbox` | A3 | 读取当前可见人工待办列表 | 总览、Copilot |
| `summarize_review_inbox` | A3 | 读取 open/high/overdue/snoozed 待办摘要 | 总览、Copilot |
| `place_real_order` | A5 disabled | 真实下单占位 | 始终阻断 |

补充说明：

- active risk policy 会影响研究、提醒、回测和拟单草案，但不会触发自动交易。
- `place_real_order`、`/api/settings/tools` 继续保持阻断；系统能力图不新增 TeamRun 或 `/api/team-runs`。
- `create_paper_order` 不进入 Tool Bridge；paper order 只能由用户显式 HTTP/UI 创建。
- review inbox action 只允许通过 HTTP/UI 写 `review_inbox_state`；Tool Bridge/Copilot 不提供 write inbox tool。
- Paper portfolio baseline 固化在 `app_config["paper_portfolio_baseline"]`；projection 只回放 frozen baseline + `paper_filled` orders。
- Copilot 的 inbox / decision journal / paper portfolio intents 维持只读，不会替用户创建 paper order、snapshot、report。

关键规则：

- A2 工具只服务研究和证据收集。
- A3 工具可读取组合风险，但不生成交易草案。
- A4 只生成拟单草案，需要用户确认，不能自动下单。
- A4 可生成交易前审查，但不能替用户创建 paper order。
- 拟单草案状态机固定为 `pending_user_confirmation -> confirmed_no_execution | rejected | expired`；过期确认必须 hard-block 并要求重新生成。
- A5 在 V1 没有可执行路径，真实交易请求必须失败。
- Paper Sandbox 只写 `paper_order`，绝不改写 `holding_position`。
- Paper Portfolio 只做 projection/snapshot，不回写真实 `holding_position`，也不会因为 holdings import 而漂移 baseline。
- 所有已知工具执行都写入 `tool_execution` ledger，记录 `domain/arguments/status/authority/evidence/source_mode`。
- 所有工具输出统一进入 `tool_result`，final 可通过 `tool_evidence_refs` 回链证据。
- 策略回测只读研究；`candidate_actions` 与 Copilot final `execution_guard` 都必须显式 `auto_trade=false`。
- 未知 DeerFlow 工具只透传 SSE，不写本地 ledger。
- 盯盘规则评估必须由本地确定性引擎执行；Copilot 只解释事件，不参与规则判定。

## 任务、报告、审计的关系

```text
AI 运行
  -> 创建 AgentTask
  -> 产生 SSE Events
  -> DeerFlow Adapter
  -> WorkbenchToolBridge
  -> 调用 Tools
  -> 保存 ToolExecution
  -> 生成结构化结果
  -> 保存 Report
  -> 写入 AuditLog
```

关键规则：

- 深研任务写入任务和报告。
- 报告页展示模板、质量检查、证据引用和 Markdown 预览，全部走真实 API。
- 工具执行摘要写入 `tool_execution`，任务详情页和任务 SSE 回放直接消费它。
- 风险复核写入任务和审计。
- 调仓草案必须写入审计。
- 失败重试必须写入审计。
- 真实下单在 V1 被 PermissionGuard 阻断。

## 数据降级关系

所有页面都应能表达数据健康状态：

- 正常：显示完整数据、来源、更新时间。
- 降级：显示部分数据、缺失来源和影响范围。
- 失败：保留页面骨架，提示无法生成可靠结论。

AI 报告中必须展示数据源和更新时间，避免把降级数据包装成确定结论。

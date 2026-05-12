# 单用户本地版 AI Stock Workbench 服务架构

## Summary

采用“模块化单体 + 本地单用户部署”架构：一个 Python 后端服务承载 API、DeerFlow agent runtime、股票工具适配、任务流、报告、审计和设置管理。内部按清晰模块边界组织，未来如有需要可拆为独立服务，但 V1 不引入微服务复杂度。

```text
Prototype / Future Web UI
  -> Workbench API（FastAPI + SSE）
    -> Application Services
      -> Context Builder
      -> MonitorService
      -> StrategyService
      -> RebalanceDraftService
      -> PreTradeReviewService / PaperTradingService / PaperPortfolioService
      -> ReviewInboxService
      -> Copilot Service（declarative skill_trace）
      -> DeerFlow adapter boundary
      -> Workbench Tool Bridge / ToolExecutionService
      -> Stock Domain Tools（provider-router）
      -> Task / Report / Audit
      -> Settings / Permission Guard
    -> Local Persistence（SQLite + local files）
```

默认定位：

- 单用户本地工作台。
- 不做 SaaS、多租户、多人权限。
- 不接真实交易。
- AI 可研究、盯盘、风控、调仓规划、生成拟单草案与交易前审查，但不能自动下单，也不能代用户创建 paper order。
- v0.19 只收束一条 closed-loop golden path，不新增新的 runtime、DB 或执行模块。

## 后端模块边界

```text
backend/
  api/
    routes_overview.py
    routes_watchlist.py
    routes_holdings.py
    routes_stock.py
    routes_market.py
    routes_monitor.py
    routes_strategy.py
    routes_tasks.py
    routes_reports.py
    routes_settings.py
    routes_copilot.py
  app_services/
    context_builder.py
    intent_router.py
    monitor_service.py
    strategy_service.py
    rebalance_draft_service.py
    pre_trade_review_service.py
    paper_trading_service.py
    paper_portfolio_service.py
    permission_guard.py
    copilot_service.py
    task_service.py
    tool_execution_service.py
    report_service.py
    audit_service.py
  agent_runtime/
    deerflow_client.py
    tool_bridge.py
    skill_registry.py
    stream_adapter.py
    result_normalizer.py
  stock_domain/
    quote_tools.py
    history_tools.py
    intel_tools.py
    portfolio_tools.py
    risk_tools.py
    backtest_tools.py
    report_tools.py
  persistence/
    db.py
    repositories.py
    file_store.py
  config/
    providers.py
    models.py
    skills.py
```

职责划分：

- `api`：只处理 HTTP/SSE 输入输出，不写业务推理。
- `app_services`：组合业务流程，构造上下文，调用 agent/runtime/tool。
- `StrategyService`：策略库与回测唯一业务入口；负责 strategy CRUD、append-only backtest run、历史查询与审计。
- `RebalanceDraftService`：拟单草案唯一业务入口；负责创建、读取、确认、驳回、懒过期和 DecisionContext 兼容摘要。
- `PreTradeReviewService`：交易前审查唯一业务入口；负责 confirmed draft 校验、风险策略精确匹配、quote snapshot 和 execution_guard 固化。
- `PaperTradingService`：Paper Sandbox 唯一业务入口；负责从 review 生成本地 paper order ledger，并保证不修改真实持仓。
- `PaperPortfolioService`：Paper Portfolio 唯一业务入口；负责 persisted baseline、paper order projection、snapshot append-only 和 since-baseline 绩效归因。
- `ReviewInboxService`：Human Review Inbox 唯一业务入口；负责从 source object 动态生成待办、应用 dismiss/snooze/done overlay，并计算 open/high/overdue/snoozed summary。
- `closed_loop_smoke.py`：deterministic acceptance smoke；用临时 DB/files root 串完整 golden path，只打印关键 ID 和 summary。
- `ReportService`：报告模板、生成、导出、质量检查唯一业务入口；负责 code-first registry、append-only quality check 和 Markdown 归档。
- `agent_runtime`：封装 DeerFlow 和 Workbench Tool Bridge，不让 UI 或业务层直接依赖 DeerFlow 细节；默认 stub，`WORKBENCH_DEERFLOW_MODE=embedded` 时动态接入 embedded client，失败自动回退 stub。
- `stock_domain`：通过 provider-router 暴露稳定工具接口；v0.21 起 A 股 `quote/history/intel/market_review/sectors` 优先走 AKShare，多接口 best-effort 聚合后回落到 `mock_adapter`。
- `persistence`：本地 SQLite 和文件存储。
- `config`：Provider、Model、Skill、Tool 权限配置。

## 核心服务关系

```text
Copilot Request
  -> CopilotSessionService（copilot_session / copilot_message）
  -> CopilotContextBuilder（page-scoped condensed context）
  -> IntentRouter
  -> SkillRegistry
  -> declarative skill_trace
  -> ContextBuilder
  -> MonitorService
  -> PermissionGuard
  -> DeerFlowClient.stream()
  -> WorkbenchToolBridge（tool_call/tool_result）
  -> ToolExecutionService（tool_execution ledger）
  -> ResultNormalizer
  -> TaskService / ReportService / AuditService
  -> SSE events
```

关键规则：

- DeerFlow 是唯一 agent runtime。
- `MonitorService` 是盯盘规则、状态、事件、loop 和解释能力的唯一业务入口。
- `StrategyService` 是策略库、回测和历史读取的唯一业务入口；`routes_strategy` 不直接调用领域 helper。
- `RebalanceDraftService` 是拟单草案唯一业务入口；`routes_holdings`、`routes_rebalance_drafts`、`WorkbenchToolBridge` 不直接拼装 draft payload。
- `PreTradeReviewService` 是交易前审查唯一业务入口；`routes_pre_trade_reviews`、Tool Bridge、Copilot 都不直接拼装 review payload。
- Tool Bridge 的 `create_pre_trade_review` 只接受显式 `draft_id`；Copilot 若无法从受控上下文解析 confirmed draft，就必须失败并写 `tool_execution.failed`。
- `PaperTradingService` 是 paper sandbox 唯一业务入口；`routes_paper_orders` 不直接计算 symbol/price/quantity。
- `PaperPortfolioService` 是 paper portfolio 唯一业务入口；`routes_paper_portfolio`、Tool Bridge 和 report source 只通过它读 projection/snapshot，不读取 live holdings 作为 baseline。
- `ReviewInboxService` 是 review inbox 唯一业务入口；`routes_review_inbox`、Tool Bridge 和 Copilot 都不能直接拼装待办 payload 或回写 source object。
- Copilot 的 review inbox / decision journal / paper portfolio intents 只能自动执行低风险本地研究动作；不能代用户确认草案、创建 paper order、关闭 journal 或 mark inbox done。
- `CopilotContextBuilder` 只输出页面级摘要、符号摘要、任务/报告/待办引用，不输出 secret、完整持仓、完整历史、完整报告 Markdown 或完整工具参数。
- `ExecutionPolicy` 只约束 Chat/DeerFlow 自动工具调用；页面/API 显式动作仍走对应 service 的权限与状态机。
- `ReportService` 是模板、报告、质量检查和导出的唯一业务入口；`routes_reports`、`routes_stock`、Copilot 和 Tool Bridge 不直接拼接 repo payload。
- DeerFlow embedded client 只从 `DeerFlowClientAdapter` 内部接入；`DeerFlowEventMapper` 将上游 `values`、`messages-tuple`、`custom`、`end` 映射到 Workbench SSE。
- Workbench Tool Bridge 是 agent runtime 边界内调用本项目股票、持仓、风险和拟单草案能力的唯一工具桥。
- Tool Bridge 只执行注册工具，并在执行前通过 `PermissionGuard` 校验权限等级。
- Tool Bridge 对已知工具执行写入 `tool_execution` ledger，记录 `run_id/task_id/call_id/domain/arguments/source_mode` 和 `succeeded/blocked/failed` 状态。
- `place_real_order` 只作为 disabled 工具占位，任何调用都被 `PermissionGuard.block_real_order()` 阻断。
- daily_stock_analysis 只作为领域工具箱，不作为第二套 agent 编排。
- `skill_trace` 是声明式元数据，用于解释 Copilot 本次可能涉及的 Skills、handoff 和权限边界；它不是进程内 Team Run runtime。
- 产品运行时不新增 `TeamRuntime`、`TeamOrchestrator`、`/api/team-runs`、`team_run` 或 `agent_step` 表。
- 多 agent 协作可以作为研发交付流程使用，但不能映射成 V1 产品运行时的独立 TeamRun 能力。
- provider-router 是股票数据边界；缺少 AKShare 依赖时自动回退到 `mock_adapter`。
- `/api/health` 和 `/api/settings` 必须暴露 `agent_runtime` 状态，包括 `mode`、`available`、`active_client`、`degraded`、`degraded_reason`、`subagent_enabled`、`plan_mode`、`client_capabilities`、`config_path`、`model_name`、`thinking_enabled`。
- 所有工具输出先归一化，再进入 AI 或页面。
- 所有 AI 结论必须带证据、置信度、反对理由、有效期、风险提示。
- 所有高风险动作进入 `AuditService`。

## Public API

```text
GET  /api/health
GET  /api/overview
GET  /api/watchlist
POST /api/watchlist/items
DELETE /api/watchlist/items/{symbol}

GET  /api/holdings
POST /api/holdings/import-preview
POST /api/holdings/import-confirm
GET  /api/holdings/risk
POST /api/holdings/rebalance-draft

GET  /api/rebalance-drafts
POST /api/rebalance-drafts
GET  /api/rebalance-drafts/{draft_id}
POST /api/rebalance-drafts/{draft_id}/confirm
POST /api/rebalance-drafts/{draft_id}/reject

GET  /api/pre-trade-reviews
POST /api/pre-trade-reviews
GET  /api/pre-trade-reviews/{review_id}

GET  /api/paper-orders
POST /api/paper-orders
GET  /api/paper-orders/{order_id}
POST /api/paper-orders/{order_id}/cancel

GET  /api/paper-portfolio
GET  /api/paper-portfolio/positions
GET  /api/paper-portfolio/performance
POST /api/paper-portfolio/snapshots
GET  /api/paper-portfolio/snapshots
GET  /api/paper-portfolio/snapshots/{snapshot_id}

GET  /api/decision-journal
GET  /api/decision-journal/summary
GET  /api/decision-journal/{entry_id}
POST /api/decision-journal/{entry_id}/link-snapshot
POST /api/decision-journal/{entry_id}/close

GET  /api/review-inbox
GET  /api/review-inbox/summary
POST /api/review-inbox/{item_key}/dismiss
POST /api/review-inbox/{item_key}/snooze
POST /api/review-inbox/{item_key}/mark-done

GET  /api/stocks/search?q=
GET  /api/stocks/{symbol}/context
POST /api/stocks/{symbol}/research

GET  /api/market/review
GET  /api/market/sectors

GET  /api/monitor/events
GET  /api/monitor/status
GET  /api/monitor/rules
POST /api/monitor/start
POST /api/monitor/pause
POST /api/monitor/rules
DELETE /api/monitor/rules/{rule_id}
POST /api/monitor/evaluate-once
GET  /api/monitor/stream

GET  /api/strategies
POST /api/strategies
GET  /api/strategies/{id}
PUT  /api/strategies/{id}
DELETE /api/strategies/{id}
POST /api/strategies/{id}/backtest
GET  /api/strategies/{id}/backtests
GET  /api/backtests/{run_id}

GET  /api/tasks
GET  /api/tasks/{task_id}
GET  /api/tasks/{task_id}/stream
POST /api/tasks/{task_id}/retry

GET  /api/report-templates
GET  /api/reports
POST /api/reports/generate
GET  /api/reports/{report_id}
GET  /api/reports/{report_id}/quality
POST /api/reports/{report_id}/rerun-quality
POST /api/reports/{report_id}/export

GET  /api/risk-policies
POST /api/risk-policies
GET  /api/risk-policies/active
GET  /api/risk-policies/{policy_id}
PUT  /api/risk-policies/{policy_id}
POST /api/risk-policies/{policy_id}/activate

GET  /api/settings
PUT  /api/settings/providers
PUT  /api/settings/models
PUT  /api/settings/skills

POST /api/copilot/chat
GET  /api/copilot/stream/{run_id}
GET  /api/copilot/sessions
POST /api/copilot/sessions
GET  /api/copilot/sessions/{session_id}
GET  /api/copilot/sessions/{session_id}/messages
POST /api/copilot/sessions/{session_id}/messages
GET  /api/copilot/sessions/{session_id}/stream/{run_id}
```

恢复约束：

- 若内存中的 run state 丢失，Copilot stream 必须从持久化 `copilot_message(user)` 与 `agent_task` 恢复，不返回伪造 continuation。

不提供：

```text
GET/POST /api/team-runs
```

Team Run 在当前产品运行时不是 public API。Copilot 的多 Skill 说明通过 `skill_trace` 随 `CopilotRun`、`AgentTask` 和 SSE payload 暴露。

任务接口补充约束：

- `GET /api/tasks` 只返回任务列表，不内联 `tool_executions`。
- `GET /api/tasks/{task_id}` 返回任务原字段并附带 `tool_executions`。
- `GET /api/tasks/{task_id}/stream` 先用 `reasoning` 输出任务快照，再按 ledger 顺序回放 `tool_result/error` 摘要，最后输出 `final`。

## SSE 事件

统一格式：

```json
{
  "run_id": "run_123",
  "task_id": "task_123",
  "type": "skill_trace | tool_call | tool_result | reasoning | partial_answer | final | error",
  "payload": {},
  "created_at": "2026-05-11T18:00:00+08:00"
}
```

`skill_trace` 事件只表达“本次 Copilot run 的 Skill 声明和权限边界”。真正的推理和工具调用仍从 `DeerFlowClient.stream()` 边界输出。调仓与策略回测类 final payload 必须携带 `execution_guard.research_only=true`、`execution_guard.auto_trade=false`，并明确真实交易关闭。

报告相关补充约束：

- `ReportTemplate` 只接受 code-first registry，SQLite `report_template` 只负责可见性快照。
- `ReportQualityCheck` 只追加不覆盖；重跑质检只能新增记录并更新 `report.latest_quality_*` 摘要。
- `generate_report` 只允许基于已有 `source_type/source_id` 读取 `stock`、`monitor_event`、`backtest_run`，不能在工具内部触发新的回测、盯盘评估或交易动作。
- `paper_portfolio_review` 只读取 snapshot payload；若 report 先生成、journal 后 link snapshot，`DecisionJournalService.link_snapshot()` 会补齐 `report_id`。

任务回放 SSE 约束：

- 成功 ledger 重放为 `tool_result`。
- `blocked/failed` ledger 重放为 `error`。
- 回放 payload 只包含工具摘要，不重复注入完整工具原始结果。

## DeerFlow Embedded 适配

v0.9 的接入边界：

- 默认 active client 是 `stub`，保证离线 demo 和测试稳定。
- `WORKBENCH_DEERFLOW_MODE=embedded` 时，adapter 动态导入 `deerflow.client.DeerFlowClient`；项目不 vendor、不复制 DeerFlow 源码。
- 导入或初始化失败时，adapter 继续使用 stub，并把失败原因写入 health/settings 状态。
- embedded message 不直接透传用户原话，而是包装成 prompt envelope：`user_message`、`condensed_stock_context`、精简 `skill_trace`、安全约束。
- envelope 不允许包含 secret、环境变量、完整持仓、完整自选、完整历史、完整报告或工具台账明细，也不会落库。
- `messages-tuple` 的 AI 文本映射为 `partial_answer`。
- `messages-tuple` 的 tool calls 映射为 `tool_call`。
- `messages-tuple` 的 tool message 映射为 `tool_result`。
- `values` 只映射为 `reasoning` 状态快照，不能重复输出已由 `messages-tuple` 流过的文本。
- `end` 映射为 `final`，并保留 usage metadata。
- 若 `DeerFlowClient.stream()` 是同步 generator，adapter 必须在后台线程消费并桥接回 async SSE，不能在 event loop 中直接迭代。
- stream startup failure 允许回退一次 stub；mid-stream failure 只输出 `error + final`，不再拼接 stub 第二答案，并更新 degraded 状态。
- Embedded 模式默认 `subagent_enabled=false`、`plan_mode=false`；这些是 runtime 内部参数，不在设置页暴露为 TeamRun 控制项。

## Workbench Tool Bridge

v0.8 的工具桥和执行台账边界：

- `get_stock_context`：A2，读取 `StockContext`。
- `get_daily_history`：A2，读取历史走势。
- `search_stock_intel`：A2，读取新闻、公告和证据列表。
- `get_portfolio_snapshot`：A3，读取本地持仓摘要。
- `get_active_risk_policy`：A2，读取当前 active/default 风险策略。
- `list_risk_policies`：A2，读取风险策略列表。
- `evaluate_policy_risk`：A3，按 active policy 执行组合风险扫描并写 ledger。
- `analyze_portfolio_risk`：A3，兼容旧工具名，但内部转发到 policy-aware 风险扫描。
- `list_strategies`：A2，读取持久化策略库。
- `run_strategy_backtest`：A3，触发确定性本地回测并写 `tool_execution`。
- `get_backtest_result`：A2，读取 append-only 回测历史。
- `generate_draft_order`：A4，创建持久化拟单草案，输出必须包含 `draft_id`、`draft_status`、`auto_trade=false`。
- `list_rebalance_drafts`：A4，列出持久化拟单草案。
- `get_rebalance_draft`：A4，读取单条拟单草案详情。
- `place_real_order`：A5 disabled，占位表达未来执行代理边界，V1 永远阻断。

运行规则：

- stub 模式也要产生真实 `tool_call/tool_result`，用于 demo 和测试验证工具契约。
- stub/embedded 模式调用 bridge 时都要传 `run_id/task_id/call_id/source_mode`。
- embedded 模式遇到 Workbench 工具名时，在 `DeerFlowClientAdapter` 边界先输出 `tool_call`，再由 `WorkbenchToolBridge` 执行并输出 `tool_result`。
- 成功执行写 `status=succeeded`；`PermissionDenied` 写 `status=blocked` 后继续抛出；其他异常写 `status=failed` 后要收口成 `error + final`，避免 SSE 崩掉。
- `place_real_order` 永远落为 `blocked`；未知工具不写 ledger。
- 拟单草案状态机固定为 `pending_user_confirmation -> confirmed_no_execution | rejected | expired`；confirm 命中过期草案必须返回 `409` 并要求重新生成。
- `strategy-analyst` skill 的回测触发必须映射到已知 `run_strategy_backtest`，不能作为 unknown DeerFlow tool 透传。
- final payload 可以附带 `tool_evidence_refs`，用于报告和审计解释数据来源。
- `tool_evidence_refs` 只能来自真实执行过的 Workbench 工具结果，不能根据计划中的 `skill_trace` 虚构。
- `/api/settings` 的 `tools` 只展示运行时注册表；V1 不允许通过设置 API 覆盖工具契约或启用 `place_real_order`。
- `/api/settings` 额外暴露 `risk_policy` 摘要，用于设置页、持仓页、盯盘页和策略页展示 active policy。
- Tool Bridge 不新增 TeamRun，不把工具注入 DeerFlow 内部工具系统。
- Tool Bridge 只调用本项目自有 adapter，不复制 DeerFlow 或 daily_stock_analysis 源码。

## Local Persistence

本地单用户默认：

- SQLite：业务状态、任务、报告索引、审计日志、配置。
- `risk_policy`：风险偏好与仓位规则专表；`activate` 在事务内清空其他 active/default，保证只有一个当前策略。
- `strategy_spec`：策略库，保留 `payload` 与 `strategy_type/enabled/risk_level/tags` 等可检索列。
- `backtest_run`：append-only 历史回测，保留 `payload` 与 `strategy_id/strategy_name/strategy_type/degraded` 等可检索列，并固化 `risk_policy_ref`。
- `monitor_rule` / `monitor_status` / `monitor_event`：持久化盯盘规则、状态与事件。
- `rebalance_draft`：持久化拟单草案，保留 `symbol/status/authority_level/target_weight_pct/valid_until` 可检索列，并固化 `risk_policy_ref` 与有效期来源。
- `tool_execution` 表：任务工具执行台账，用于任务详情和 SSE 回放。
- Local files：报告 Markdown/HTML、上传文件、agent artifacts。
- 内存缓存：实时行情、市场复盘、短期工具结果。
- 可选后续增强：DuckDB 存历史行情和回测数据。

不引入：

- Redis。
- Kafka。
- Celery 分布式队列。
- 多租户数据库。
- 云对象存储。

后台任务 V1 使用进程内 async task runner；任务状态写 SQLite。

## Test Plan

必须覆盖：

- 股票搜索：输入代码、名称、拼音后返回 `StockContext`。
- 自选链路：添加自选 -> 打开个股 -> 生成深研任务 -> 生成报告。
- 持仓链路：导入持仓预览 -> 确认导入 -> 风险诊断 -> 调仓方案草案。
- 盯盘链路：开启规则 -> 生成事件 -> 事件进入个股/持仓复核。
- Copilot 链路：用户自然语言请求 -> intent routing -> skill selection -> SSE 输出。
- Tool Bridge 链路：Copilot/DeerFlow tool call -> 权限校验 -> Workbench 工具执行 -> `tool_result` -> final `tool_evidence_refs`。
- Draft Review 链路：显式 A4 请求 / `generate_draft_order` -> `rebalance_draft` 持久化 -> HTTP confirm/reject 更新状态 -> 审计记录确认结果但不执行真实交易。
- Ledger 链路：bridge 保存 `tool_execution` -> `GET /api/tasks/{task_id}` 返回记录 -> `GET /api/tasks/{task_id}/stream` 回放摘要。
- 权限链路：研究允许，拟单允许，真实下单阻断。
- 审计链路：深研任务、风险复核、拟单草案、失败重试都写入 audit log。
- Skill Trace 链路：Copilot run 返回 skills，任务保存 `skill_trace`，SSE 输出声明式 `skill_trace`，但 `/api/team-runs` 保持不存在。
- Smoke 链路：`scripts/deerflow_smoke.py` 通过 `create_services` + `CopilotService.stream_run()` 验证 runtime status、SSE event types、`final/error`，不启动长期服务、不写 repo 文件。
- 数据降级：主数据源失败时返回降级状态，报告中展示数据源和更新时间。
- DeerFlow 集成：stream 事件能被转换为统一 SSE 事件。
- 结构化输出：AI 输出不符合 schema 时进入修复或失败状态，不直接污染报告库。

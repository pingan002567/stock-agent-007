# AI Stock Workbench 文档索引

本目录恢复并整理此前对话中沉淀过的 AI 股票工作台设计结论（含原 `docs/` 目录内容）。当前文档不是逐字节恢复旧文件，而是基于历史对话日志、已重建原型和当前后端代码重新归档，保证产品语义、架构边界和实施路线可继续演进。

## 文档列表

- [ai_stock_workbench_feasibility.md](./ai_stock_workbench_feasibility.md)
  - DeerFlow 作为 embedded Python agent runtime 的可行性。
  - daily_stock_analysis 作为股票领域工具箱的边界。
  - V1 风险、目录建议、集成路线和版权边界。

- [ai_stock_workbench_north_star.md](./ai_stock_workbench_north_star.md)
  - 完全 AI 驱动股票工作台的北极星设计。
  - AI 研究、盯盘、风控、调仓规划、执行代理的职责分级。
  - 权限等级、人工确认和长期演进路线。

- [frontend_interaction_design.md](./frontend_interaction_design.md)
  - 产品原型的前端交互设计。
  - 左中右三栏、总览、自选、持仓、个股、市场、盯盘、策略、任务、报告、设置和 AI Copilot 的页面职责。
  - AI Chat 简化设计和右侧全局 Copilot 面板。

- [menu_information_architecture.md](./menu_information_architecture.md)
  - 左侧菜单排序、命名和信息架构。
  - 自选、持仓、个股搜索、板块信息应放置的位置。

- [system_capability_map.md](./system_capability_map.md)
  - 当前系统能力之间的关系图。
  - 页面、业务对象、AI Skills、任务、报告、审计之间的联动。

- [daily_stock_analysis_migration.md](./daily_stock_analysis_migration.md)
  - daily_stock_analysis 值得吸收的能力。
  - 先吸收基础能力的分阶段策略。
  - 避免源码复制和版权风险的 adapter 边界。

- [ai_runtime_settings_design.md](./ai_runtime_settings_design.md)
  - Provider、Model、Skill、Tool、Profile 在设置页的设计。
  - 参考 DeerFlow 的 agent runtime 思路，定义配置对象和权限边界。

- [service_architecture.md](./service_architecture.md)
  - 单用户本地版服务架构。
  - FastAPI、DeerFlow embedded runtime、stock domain adapter、SQLite、本地文件、SSE 的模块关系。

- [production_readiness_assessment.md](./production_readiness_assessment.md)
  - 当前系统距离生产级还有多远的阶段评估。
  - 分别评估产品闭环、数据、AI/runtime 和前端承载层进度。
  - 给出当前最关键的生产化差距与优先级。

- [runnable_web_demo_plan.md](./runnable_web_demo_plan.md)
  - 从架构骨架推进到可运行 Web Demo 的实施计划。
  - 当前后端 demo 与完整产品原型的关系。

- [AI_CHAT_BUBBLE.md](./AI_CHAT_BUBBLE.md)
  - AI Chat 气泡展示与对话流。
  - 前端气泡渲染机制、对话流状态机、诊断问题。

- [AI_CHAT_SESSION.md](./AI_CHAT_SESSION.md)
  - AI Chat 会话与消息架构。
  - 会话管理、消息流、前端状态机设计。

- [CHAT_BUBBLE_REDESIGN.md](./CHAT_BUBBLE_REDESIGN.md)
  - AI Chat Bubble 闭环改造方案。
  - 前端 CopilotPanel 的设计定稿与执行追踪。

- [STACK_DECISIONS.md](./STACK_DECISIONS.md)
  - 后端关键技术栈决策记录。
  - 项目架构的强依赖文档。

## 当前关键产物

- 前端工程位于 **[frontend/](../frontend/)**（React + TypeScript + Vite）
- 后端入口：[backend/app.py](../backend/app.py)
- 运行方式：`bash scripts/dev.sh`（启动 backend:6666 + frontend:8888）

## 设计原则

1. 用户不是在使用“股票聊天机器人”，而是在使用“AI 驱动的投研与持仓工作台”。
2. 自选、持仓、个股是用户资产视角的核心入口；市场和板块提供解释语境。
3. AI 可以主动盯盘、生成研究、诊断风险、规划调仓，但 V1 不自动真实下单。
4. DeerFlow 只承担 agent runtime 和编排边界；daily_stock_analysis 只作为领域能力参考和工具适配来源。
5. 所有高风险输出都需要证据、置信度、反对理由、有效期、权限等级和审计记录。
6. `skill_trace` 是 Copilot 的声明式解释元数据，不是产品运行时 Team Run；多 agent 协作只作为研发交付流程。
7. DeerFlow embedded client 只通过 `DeerFlowClientAdapter` 可选启用；默认 stub，失败自动回退，且不暴露 TeamRun/sub-agent 产品入口。
8. `WorkbenchToolBridge` 是 Copilot/DeerFlow 调用股票、持仓、风险和拟单草案能力的唯一桥接层；`place_real_order` 始终 blocked。
9. Embedded prompt 只能接收精简 envelope，不把本地 secret/env/full holdings/full watchlist/full history/full report/ledger detail 透传给 DeerFlow。
10. `MonitorService` 负责持久化盯盘规则、状态和事件；规则评估必须本地确定性执行，不调用 LLM。
11. `StrategyService` 负责持久化策略库和 append-only 回测历史；Copilot 触发回测必须走已知 ToolBridge 工具并写 ledger。
12. `ReportService` 负责 code-first 模板、报告生成、append-only 质量检查和 Markdown 归档；报告页与 Demo 必须走真实 API，不使用占位质检数据。
13. `RebalanceDraftService` 负责拟单草案持久化、确认/驳回、懒过期和审计；确认只能由 HTTP/UI 显式触发，不能暴露为 ToolBridge 工具。
14. `ReviewInboxService` 负责 Human Review Inbox 动态待办与 overlay；dismiss/snooze/done 只能写 `review_inbox_state`，不能回写 source object。
15. v0.19 closed loop RC 只收束一条 golden path；Copilot 的 inbox / journal / paper 复盘 intents 维持只读，不会替用户创建 paper order、snapshot 或 report。
16. v0.20 AI Chat 是统一指挥入口：会话、上下文卡、工具过程卡和结果卡都可持久恢复；低风险本地研究动作可自动执行，高风险状态变更仍需页面显式触发。

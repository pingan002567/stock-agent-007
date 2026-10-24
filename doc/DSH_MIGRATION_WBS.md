# 《若迁移 DSH》详细工作分解（WBS）

> 版本：v0.1 · 状态：方案（未决策）· 作者：agent 评估
> 对象：stock-agent-007（本地 AI 投资工作台）
> 基线引擎：DeerFlow 2.0 Harness（`deerflow-harness`，Python SDK）
> 目标引擎：DeepSeek Harness（DSH，TypeScript/Cordis，本机安装版 `0.2.0-rc.2`）
> 估算口径：1 名全栈（Python + TS）+ 0.5 名前端；人日为弹性估算，误差 ±30%，不含评审/等待。

---

## 0. 决策摘要与推荐目标态

### 0.1 两个可选目标态

| 目标态 | 内容 | 工作量 | 风险 |
|---|---|---|---|
| **E1：引擎替换（推荐）** | 保留 React/Tauri 前端 + FastAPI 域服务，仅把 `backend/agent_runtime/` 里的 DeerFlow 引擎换成 DSH；域工具经 **MCP** 桥回 Python | 中（约 45–60 人日） | 中 |
| **E2：壳替换（独立/可选）** | 额外采用 DSH 自带 Web GUI / 桌面壳，React 应用降级为域页面或退役 | 高（额外 20–30 人日） | 高 |

**本 WBS 以 E1 为主线（Phase 1–5、7），E2 单独列为 Phase 6，可独立决策。**

### 0.2 关键架构决策（前置）

| 决策点 | 推荐 | 理由 |
|---|---|---|
| 域工具如何进 DSH | **Python MCP server**（stdio 或 HTTP/SSE）暴露 72 个工具 + `permission_guard` | DSH 原生是 MCP client；项目已接线 MCP（`/api/runtime/mcp`、`list_mcp_servers`、`extensions_config.json`）；保留全部 Python 数据生态 |
| 引擎进程形态 | `dsh --profile sdk`（JSON-RPC stdio）作为 FastAPI 侧子进程，替代 `DeerFlowClientAdapter` | 与现有 `from_env()` 三态（direct/embedded/stub）可一一对应 |
| 前端协议 | **保持不变**（`SSEEvent` 八事件契约），只换后端事件映射层 | 前端零改动，迁移风险最小 |
| 会话真相 | DSH session 为真相，SQLite 继续做投影 | 延续现有“checkpoint 是真相、SQLite 是投影”纪律 |
| 权限 | 双层：DSH approval policy（外层）+ Python `permission_guard`（内层，`place_real_order` 永久阻断） | 纵深防御，不把金融护栏只押在单层 |

### 0.3 非目标（迁移期间不做）

- 不重写 `backend/stock_domain/`（11 个 `*_tools.py`）、持仓/盯盘/回测/风控页面。
- 不引入多用户、云沙箱、IM 网关（仍保持单用户本地）。
- 不做“双引擎并跑支持两套产品”，避免双账本。
- 不改动 `WorkbenchRepository` / SQLite schema（除非投影表新增字段）。

---

## 1. 现状盘点：迁移面清单

> 全部文件路径相对仓库根，行数为迁移前实测。

| 迁移面 | 文件（行数） | 迁移动作 |
|---|---|---|
| 引擎适配层 | `backend/agent_runtime/deerflow_client.py`（1,522） | **重写**为 `dsh_client.py` |
| 运行时配置生成 | `backend/agent_runtime/deerflow_config.py`（681，约 30 个配置键） | **废弃**，改为 DSH profile / 环境变量 |
| 工具桥 | `backend/agent_runtime/tool_bridge.py`（2,031） | 拆分为“MCP 侧直连域服务”+“DSH 侧薄适配” |
| 工具注册 | `backend/agent_runtime/tools.py`（1,035，**72 工具**：A2×27 / A3×38 / A4×6 / A5×1 阻断） | 反射包装进 MCP server |
| 流式适配 | `backend/agent_runtime/stream_adapter.py`（98） | **复用**（SSE 心跳/编码逻辑与引擎无关） |
| 技能加载 | `skill_registry.py`(42) / `skill_specs.py`(183) / `extensions_store.py`(83) | 改读 DSH skill 目录 + `extensions_config.json` 语义 |
| 人机交互 | `human_input.py`（274） | 映射到 DSH `ask_user` / approval |
| 编排服务 | `app_services/copilot_service.py`（2,072）+ `copilot_cost.py`(47) + `copilot_session_state.py`(70) + `copilot_errors.py`(80) | 保留 60–70% 结构，替换引擎调用与用量来源 |
| 权限 | `app_services/permission_guard.py`（A1–A5，`block_real_order`） | **保留**，作为 MCP 内层闸 |
| API 层 | `api/routes_copilot.py` + `schemas.py`（`SSEEvent`/`AgentTask`/`ToolExecution`） | 契约不变，仅事件来源换 |
| 前端 | `frontend/src/api/copilot.ts`（8 事件常量）、`humanInput`、copilot 面板 | E1 下零改动 |
| 技能资产 | `skills/SOUL.md` + `skills/custom/*/SKILL.md`（11 个，frontmatter `name/description/allowed-tools`） | 平移为 DSH skill 格式（同 SKILL.md 约定，需改 frontmatter 与 allowed-tools 语义） |
| 域层 | `stock_domain/*_tools.py`（11）、`app_services/*`（数据源/风控/回测/纸面交易） | **不动** |
| 测试 | `tests/`（`deerflow`、`ai_regression` 标记）、`scripts/*_smoke.py` | 改造标记与 fixture，逻辑用例保留 |

---

## 2. 能力映射表（DeerFlow → DSH）

### 2.1 配置段映射

| DeerFlow 配置键 | DSH 对应机制 | 说明 |
|---|---|---|
| `models` / `model` | DSH 模型设置 + `pi-ai` 多 provider 适配 | 现用 deepseek-chat（OpenAI 兼容），DSH 侧同样走 OpenAI 兼容端点 |
| `tools` / `tool_groups` / `tool_overrides` | MCP 工具 + DSH 原生工具 | `group` 语义由 MCP server 的 tool 列表替代 |
| `skills` / `skill_evolution` | DSH `skill` 工具 + `skills/` 目录 | 关闭“技能自进化”（现为关闭态） |
| `subagents` / `custom_agents` | DSH `subagent` / `subagent_fork` 工具 | 8 个投研子代理配置平移 |
| `sandbox`（`allow_host_bash:false`、`readonly`） | DSH fs sandbox 策略（workspace-write / danger-full-access）+ 审批策略 | `allow_host_bash:false` → 默认不授 danger-full-access |
| `guardrails`（`denied_tools`、`security_fail_closed`） | DSH approval policy（ask/never）+ Python `permission_guard` | `place_real_order` 双闸阻断 |
| `memory`（`max_facts`、`max_injection_tokens`、`fact_confidence_threshold`） | DSH 会话级记忆（如 `memory`/长期记忆能力） | 语义接近，参数对齐需适配 |
| `token_budget`（`warn_threshold`/`hard_limit`） | DSH `token-meter` | 迁移阈值 |
| `summarization` / `loop_detection`（`circuit_breaker`） | DSH compaction（`compaction-basic` + `tool-result-pruner`） | 对齐触发条件 |
| `tool_output`（`max_chars`/`max_words`） | DSH 工具结果截断策略 | 对齐上限 |
| `tool_search` | DSH 对 MCP 工具的延迟发现（如 `tool_search` 语义） | 仅对 MCP 工具生效的开关平移 |

### 2.2 事件映射（后端内部，前端无感）

| 现有 `SSEEvent.type` | DSH 来源 | 备注 |
|---|---|---|
| `reasoning` | DSH thinking/reasoning 消息 | 保持流式增量 |
| `partial_answer` | DSH 文本增量 | 保持流式增量 |
| `tool_call` / `tool_result` | DSH 工具调用/结果（含 MCP 域工具） | `call_id` 对齐 |
| `final` | DSH 回合结束消息 | 附 `skill_trace` |
| `clarification` | DSH `ask_user`（用户问题/确认） | 映射 `human_input` |
| `skill_trace` | 由 DSH 的 `subagent`/`skill`/`workflow`/`todo` 事件聚合投影 | 需重建聚合器 |
| `error` | DSH 异常/熔断 | 复用 `copilot_errors` 归类 |

### 2.3 权限映射（A1–A5）

| 现有 authority | 含义 | DSH 落点 |
|---|---|---|
| A1 | 只读 | 仅挂只读工具（quote/history/financial） |
| A2 | 研究 | MCP 只读研究工具 |
| A3 | 组合/风控写入 | 需审批的写工具 |
| A4（默认档） | 规划/草案 | 审批策略 `ask` |
| A5 | 执行（真实下单） | **双闸永久阻断**（DSH never + Python `block_real_order`） |

---

## 3. 工作分解（WBS）

### Phase 0 — 决策与基线（1.0）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 0.1 | Go/No-Go 评审 | 冻结目标态（E1/E2）、审批预算、确认 MCP 桥方案 | 评审纪要 | 0.5 天 |
| 0.2 | 基线录制 | 录制 12–15 条金句对话（含工具调用、澄清、子代理、驳回 `place_real_order`）为回归集 | `tests/fixtures/golden/` | 1.5 天 |
| 0.3 | 决策记录更新 | 改写 `doc/STACK_DECISIONS.md` §1，废止 DeerFlowClient 强依赖，写入新强依赖 | 更新后的决策文档 | 0.5 天 |
| 0.4 | 遥测基线 | 记录现引擎 token/延迟/成功率基线，供影子对照 | 基线报告 | 0.5 天 |

**验收**：金句集可离线回放；决策文档一致；基线数字留档。

---

### Phase 1 — 工具桥：Python 域 → MCP（1.1）

> 目标：72 个域工具 + 权限闸以 MCP server 暴露，DSH 可调用且与现有 `tool_bridge` 结果一致。

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 1.1 | MCP server 骨架 | 新建 `backend/mcp_server/`（FastMCP，stdio + 可选 HTTP），进程化启动，与 FastAPI 共享 `create_services()` 与 `WorkbenchRepository` | 可启动的 server | 2 天 |
| 1.2 | 工具反射导出 | 把 `tools.py` 的 72 个 `StructuredTool` 逐一映射为 MCP 工具（schema 自动生成，`authority` 作为标注保留） | 全量工具清单 + schema 快照 | 2 天 |
| 1.3 | 权限闸内嵌 | 每个工具调用前置 `permission_guard.require(...)`；`place_real_order` 无条件抛 `PermissionDenied` | 权限单测 | 1 天 |
| 1.4 | 结果/异常规整 | 复用 `result_normalizer` 与降级语义，统一 MCP 返回结构 | 规整器 | 1 天 |
| 1.5 | 对拍验证 | 对 72 工具跑“MCP 结果 == 现有 bridge 结果”对拍（golden 输入集） | 对拍报告 | 2 天 |

**依赖**：0.2（金句）、0.3（决策）。
**验收**：72/72 工具对拍一致；A5 阻断生效；MCP schema 含 authority 标注。

---

### Phase 2 — 引擎接入：DSH 客户端（1.2）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 2.1 | DSH 进程适配 | 新建 `backend/agent_runtime/dsh_client.py`：spawn `dsh --profile sdk`，JSON-RPC/ACP 会话管理，三态 `direct/embedded/stub` 对应实现 | `DshClientAdapter` | 3 天 |
| 2.2 | 会话映射 | project session ↔ DSH session 双向注册表，重启可恢复 | 会话映射层 | 1.5 天 |
| 2.3 | 事件映射器 | 新建 `DshEventMapper`（DSH 事件 → 现有 `SSEEvent`），防御式消费 dict | 映射器 + 单测 | 2.5 天 |
| 2.4 | 配置生成替代 | 删除/禁用 `deerflow_config.py`，改为 DSH profile 模板 + 环境变量（模型、MCP server 端点、审批策略） | profile 模板 | 2 天 |
| 2.5 | stub 模式 | `WORKBENCH_AI_MODE=stub` 下无模型调用，供测试/CI | stub 实现 | 1 天 |

**依赖**：Phase 1。
**验收**：`/api/health` 显示 `active_client=dsh`；三态可切换；事件映射单测过。

---

### Phase 3 — 原语迁移（1.3）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 3.1 | 人格 | `SOUL.md` → DSH agent-preset / persona（保留“股神”语气、底线、`update_agent` 语义改由 DSH preset 承接） | 新 preset | 1 天 |
| 3.2 | 技能 | 11 个 `SKILL.md` frontmatter（`allowed-tools` → DSH skill 工具白名单语义）平移 | 11 个 DSH skill | 2 天 |
| 3.3 | 子代理 | 8 个 subagent 配置 → DSH `subagent` 描述/预置（researcher/valuation/catalyst 等） | 子代理预置 | 2 天 |
| 3.4 | 计划/待办 | DeerFlow TodoMiddleware → DSH `todo_write`/plan-mode，前端 checklist 投影不变 | 计划投影 | 1.5 天 |
| 3.5 | 护栏 | `denied_tools` + `security_fail_closed` → DSH approval（never for A5）+ 内层 `permission_guard` | 护栏配置 | 1 天 |
| 3.6 | 记忆 | DeerFlow memory → DSH 会话记忆（对齐 `max_facts`/置信阈值） | 记忆配置 | 1.5 天 |
| 3.7 | token 预算 | `token_budget` 阈值 → DSH `token-meter` | 预算配置 | 0.5 天 |

**依赖**：Phase 2。
**验收**：金句回放在新引擎下产物可读、语气/纪律一致；A5 仍被拒。

---

### Phase 4 — 会话 / 成本 / 观测（1.4）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 4.1 | 投影落库 | DSH 事件 → `AgentTask`/`ToolExecution`/消息 写回 SQLite（投影表） | 投影写回 | 2 天 |
| 4.2 | 成本估算 | `copilot_cost.py` 改为读 DSH token 用量（`token-meter` 事件） | 成本模块 | 1 天 |
| 4.3 | 多轮记忆投影 | `TurnSummary`/`SessionStateData` 改由 DSH 会话上下文承接，SQLite 仅 UI 快照 | 会话状态 | 1 天 |
| 4.4 | 观测替换 | Langfuse/LangSmith → DSH 侧 OpenTelemetry 导出，保留 env 开关 | 追踪配置 | 1 天 |

**依赖**：Phase 2/3。
**验收**：会话回放、成本、追踪三者与基线量级一致。

---

### Phase 5 — 前端协议对齐（1.5）

> E1 下前端**零改动**是硬约束；本阶段只做“事件契约不变量”验证与必要的聚合器修正。

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 5.1 | 八事件契约验证 | 新映射器输出逐条对拍旧 `SSEEvent`（类型/字段/时序） | 契约对拍报告 | 2 天 |
| 5.2 | `skill_trace` 聚合器 | 由 DSH subagent/skill/todo 事件重建 `skill_trace` 列表（含 `authority_level`/`status`/`blocked_reason`） | 聚合器 | 2 天 |
| 5.3 | 澄清卡 | `clarification` ↔ DSH `ask_user` 双向（用户回答回流） | 澄清链路 | 1.5 天 |
| 5.4 | 附件/图片 | 上传文件清单注入（对应 DeerFlow UploadsMiddleware → DSH 附件/`@`文件引用） | 附件适配 | 1.5 天 |

**依赖**：Phase 2/3。
**验收**：前端在 E1 分支上无需改一行即通过 e2e。

---

### Phase 6 —（可选，E2）壳替换（1.6）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 6.1 | DSH Web/桌面接入 | 用 DSH 自带 GUI 承载对话；React 应用保留为域页面（行情/持仓/回测）或 iframe/深度链接 | 壳集成 | 5 天 |
| 6.2 | 域页迁移决策 | 评估把 CRUD 页面留在 FastAPI 还是重写进 DSH 插件 | 评估文档 | 2 天 |
| 6.3 | 桌面打包 | Tauri ↔ DSH 桌面（Electron）并存策略、单实例、深链 | 打包方案 | 3 天 |

**注意**：E2 会引入“两套壳、一套域”的维护成本，仅当明确要 DSH 的 GUI/插件生态时才做。

---

### Phase 7 — 回归与上线（1.7）

| 编号 | 工作包 | 内容 | 交付物 | 工期 |
|---|---|---|---|---|
| 7.1 | 测试改造 | `deerflow` marker → `dsh`；`ai_regression` 保留；`deerflow_smoke.py`/`closed_loop_smoke.py` 重写为 `dsh_*` | 测试套件 | 2 天 |
| 7.2 | 影子运行 | 双引擎并跑（旧 DeerFlow 线上、新 DSH 影子）N 天，对拍产物/工具调用/成本 | 影子对照报告 | 3 天（并行） |
| 7.3 | 切换 | 环境变量切默认 `WORKBENCH_AI_MODE=direct(dsh)`；数据备份 | 上线发布 | 0.5 天 |
| 7.4 | 回滚预案 | 保留 `deerflow_client.py` 分支 30 天，一键切回 | 回滚手册 | 0.5 天 |
| 7.5 | 文档收口 | 更新 README/CLAUDE.md/决策文档/健康检查 | 文档 | 1 天 |

**依赖**：Phase 1–5（E1）或含 Phase 6（E2）。
**验收**：全量 pytest/vitest/playwright 绿；金句回放达标；可一键回滚。

---

## 4. 汇总

### 4.1 工期 / 人力

| 阶段 | 内容 | 工期（人日，估） |
|---|---|---|
| Phase 0 | 决策与基线 | 3 |
| Phase 1 | 工具桥（MCP） | 8 |
| Phase 2 | 引擎接入 | 10 |
| Phase 3 | 原语迁移 | 9.5 |
| Phase 4 | 会话/成本/观测 | 5 |
| Phase 5 | 前端协议 | 7 |
| Phase 7 | 回归与上线 | 7（含 3 天影子并行） |
| **E1 合计** | | **≈ 49.5 人日（约 10 周 / 1.5 人）** |
| Phase 6（可选 E2） | 壳替换 | +10 |
| **E2 合计** | | **≈ 59.5 人日** |

### 4.2 依赖与关键路径

```
0.x(基线) → 1.x(MCP桥) → 2.x(DSH接入) → 3.x(原语) ─┬→ 4.x(会话/成本) ┐
                                                    └→ 5.x(前端协议)  ┴→ 7.x(回归/上线)
                                                                   [6.x 可并行于 3–5]
```

关键路径：**0 → 1 → 2 → 3 → 5 → 7**，约 44.5 人日。
可并行：Phase 1 的 `1.5` 对拍、Phase 4、Phase 6（E2）。

---

## 5. 风险登记册

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | DSH 版本迭代快（`0.2.0-rc.2`），API 漂移 | 高 | 中 | 锁版本 + 引入与 `deerflow` 相同的“copyright-safe adapter”薄边界；升级走审计 |
| R2 | 事件语义不一一对应，`skill_trace`/`clarification` 细节丢失 | 中 | 高 | Phase 5 契约对拍 + golden 回放门禁 |
| R3 | 双账本复发（两层导演/记忆不一致） | 中 | 高 | 坚持“DSH session 为真相、SQLite 仅投影”；禁用双引擎同线 |
| R4 | 金融护栏降级（A5 下单被误开） | 低 | 极高 | 双闸（DSH never + Python `block_real_order`）+ 每轮回归必须覆盖驳回用例 |
| R5 | MCP 桥性能（72 工具 schema + 往返延迟） | 中 | 中 | stdio 常驻进程、schema 缓存、延迟对拍 |
| R6 | 前端隐性依赖旧事件时序 | 中 | 中 | E1 硬约束“前端零改动”，任何例外必须显式评审 |

---

## 6. Go/No-Go 与回滚

### 6.1 Go 条件（Phase 0 输出）

- [ ] 金句回归集（≥12 条）可离线回放且新旧结果差异已逐条标注。
- [ ] 72 工具 MCP 对拍一致率 100%（A5 阻断用例通过）。
- [ ] `dsh --profile sdk` 在本机可稳定起停，会话可跨重启恢复。
- [ ] 决策文档 `STACK_DECISIONS.md` 已更新并获评审通过。

### 6.2 回滚

1. 保留 `backend/agent_runtime/deerflow_*` 于独立分支 30 天。
2. 环境变量 `WORKBENCH_AI_MODE` 一键切回 `embedded/deerflow`。
3. SQLite 投影表只增不改，回滚无需数据迁移。
4. 回滚触发：影子期任何“产物可读性/护栏/成本”指标劣化超阈值。

---

## 7. 附：决策记录更新模板（`STACK_DECISIONS.md` §1 替换稿）

```markdown
## 1. Agent Runtime: DSH (DeepSeek Harness)

### 决策
Agent 循环统一使用 DeepSeek Harness（DSH，TypeScript/Cordis），经 `dsh --profile sdk`
JSON-RPC 子进程驱动；域工具经 Python MCP server（backend/mcp_server/）暴露；
会话真相为 DSH session，SQLite 仅投影。

### 背景
DeerFlow Harness（Python）方案因 [评审结论] 迁移至 DSH。

### 约束
- 不绕过 `DshClientAdapter` 直接调 DSH SDK；事件经 `DshEventMapper` 防御式消费。
- 域工具只能经 MCP server 暴露，不得在 DSH 侧重写域逻辑。
- `place_real_order` 双闸阻断（DSH approval never + Python permission_guard）。
- 前端 SSEEvent 八事件契约保持不变（E1）。
```

---

> 说明：本 WBS 中 DSH 能力（`dsh --profile sdk`/`acp`、MCP client、fs sandbox 策略、approval policy、`token-meter`、compaction、subagent、skill）依据本机安装版 `0.2.0-rc.2` 包结构与公开仓库 `deepseek-ai/deepseek-harness` 整理；迁移前需以目标 DSH 版本复核命令与配置键名。

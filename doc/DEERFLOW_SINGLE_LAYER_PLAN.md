# 方案：Copilot 编排收成一层（只留 DeerFlow）

> 状态：已实施（P0–P4）· 2026-09-08
> 范围：Agent 编排层。不改行情域、不换 harness、不重写工作台页面。
> 对照：[编排收成一层](../../.cursor/projects/Users-wanhui-zhang-work-project-stock-agent-001/canvases/deerflow-single-layer.canvas.tsx)（若在 Cursor 中打开）

---

## 1. 决策

**Lead Agent 是唯一导演。** Copilot 降为网关：建 thread、传权限档、映射 SSE、把事件投影到 SQLite 供 UI。意图路由、技能预算、第二份记忆、JSON envelope，全部删除。产品纪律写进 DeerFlow 原语：`SOUL.md`、`SKILL.md`、`custom_agents`、guardrails、TodoMiddleware、MemoryMiddleware、checkpoint、`token_budget`。

这不是换底座，也不是「什么都不留」。域工具、页面 CRUD、`WorkbenchToolBridge` 留下。砍的是外层那套与 DeerFlow 重复的编排。

### 1.1 原则

1. **导演只有一层。** 不允许再出现第二张意图表、第二份技能 prompt、第二份记忆、第二道委派次数闸。
2. **用户消息保持原文。** 模型看到的 `HumanMessage` 就是用户打的字，上下文用 DeerFlow 中间件注入。
3. **技能的单一属主是 SKILL.md。** Python 不再保存一份 `system_prompt`。
4. **checkpoint 是对话真相，SQLite 是投影。** 投影不得再拼回 prompt。
5. **安全用 guardrail / tool_groups，不用正则路由。** 「买入」被拒是工具拒绝，不是 IntentRouter 没匹配到。
6. **版权边界不破。** 仍只经 `DeerFlowClientAdapter` 消费 DeerFlow；不 import 内部类。

### 1.2 非目标

- 不迁移到 Pi / DeepSeek Harness。
- 不重写 `stock_domain`、持仓/盯盘/回测等页面。
- 不引入 DeerFlow Gateway、K8s sandbox、IM 网关、技能自进化。
- 不把 adapter 改回「拦截 tool_call 再执行一遍」。
- P0–P4 不要求打开 Docker 沙箱写盘；那是另一条能力线。

### 1.3 否决的替代

| 方案 | 否决原因 |
|---|---|
| 外层当导演、关掉 DeerFlow 子代理/记忆 | 等于手写 SuperAgent，放弃已接线的原生能力 |
| 两层都留、只「对齐」预算数字 | 双账本问题原样在 |
| 换成 Pi | 语言与产品不匹配，见此前成本评估 |

---

## 2. 现状（要拆的双层）

一轮请求今天的路径：

```
消息
 → IntentRouter.route()                         # copilot_service.py create_run
 → INTENT_BUDGETS + _build_skill_trace()        # 预声明「可能跑谁」
 → CopilotContextBuilder.build(intent=...)      # 按意图预取持仓/风控
 → prompt_envelope JSON（预算、trace、摘要、TurnSummary）
 → DeerFlowClient.stream(envelope, subagent/plan 按 intent)
 → 中间件 + Lead Agent + task() + 域工具
 → Copilot 再观察 task 事件回写 skill_trace、核对 required_skills
 → SQLite 落消息；TurnSummary 进内存，下一轮再塞回 envelope
```

对应文件：

| 外层导演 | 路径 |
|---|---|
| 意图正则 | `backend/app_services/intent_router.py` |
| 预算 / 技能表 / 重复 prompt | `backend/agent_runtime/skill_specs.py` |
| SkillRegistry | `backend/agent_runtime/skill_registry.py` |
| envelope | `backend/agent_runtime/prompt_envelope.py` |
| 会话摘要回灌 | `backend/app_services/copilot_session_state.py` |
| 按 intent 预取 | `backend/app_services/copilot_context_builder.py` |
| 默认 final 字段 | `backend/agent_runtime/result_normalizer.py` |
| 编排主循环 | `backend/app_services/copilot_service.py`（约 1774 行） |
| 栈决策（已过时） | `doc/STACK_DECISIONS.md` §1 约束仍写「必须 envelope、subagent 锁定 False」 |

内层导演已在用：`deerflow_config.py` 生成的 skills / subagents / memory / guardrails / token_budget / loop_detection；`stream(..., thread_id=session_id)`。

---

## 3. 目标形态

```
SPA
 → POST /api/copilot/sessions/{id}/messages
 → 薄网关：thread_id=session_id，authority → tool_groups，uploads
 → DeerFlowClient.stream(message=用户原文)
 → DynamicContext（page / symbol / authority）
 → Memory / Summarization / Guardrail / Todo / Clarification
 → Lead Agent
      ├─ 直接调 Workbench 域工具
      └─ task(stock-researcher | risk-officer | …)
 → adapter 映射 SSE → 投影 SQLite → UI
```

Lead Agent 的输入：

- `SOUL.md`（身份、研究-only、禁止泄露路径/密钥）
- 已启用技能的 name + description（渐进加载，激活才读 SKILL.md 全文）
- 动态上下文：当前页、锚定代码、本轮权限档
- checkpoint 历史
- `memory.json` 事实

Lead Agent **不得**看到：`envelope_version`、intent 名、预生成 skill_trace、`delegation_budget`、`TurnSummary`、完整持仓/自选/ledger。

### 3.1 CopilotService 最终职责（网关）

保留：

- 会话 CRUD（session 行仍映射 DeerFlow thread）
- `stream()` → SSE
- 上传 / 列出 / 删除 thread 文件
- reconnect / test-connection
- 把 stream 事件投影进 `copilot_message`（只写，不读回模型）
- 把 `task()` 事件投影成 UI 用的 observed skill 链（无预声明）

删除：

- `IntentRouter.route`
- `_build_skill_trace` / `_budget_compliance` / 预发 `skill_trace` SSE
- `render_prompt_envelope`
- `TurnSummary` 回灌
- `ResultNormalizer` 补默认 confidence / counter_reasons
- 按 intent 选择 `subagent_enabled` / `plan_mode`（改为常开，见 §5.1）

### 3.2 职责迁移表

| 现在 | 迁到 | 落地要点 |
|---|---|---|
| IntentRouter | SKILL.md `description` + Lead Agent | 技能描述写触发场景；模型选技能或直接调工具 |
| 「买入」拦截 | guardrails `denied_tools` + SOUL.md | 已拒绝 `place_real_order` / `confirm_rebalance_draft`。确认草案继续只走 HTTP |
| INTENT_BUDGETS 白名单 | 全部 custom_agents 对 Lead 可见 | 简单问题靠 description 约束零委派，不靠 Python 白名单 |
| required `risk-officer` | `rebalance-planner/SKILL.md` | 「收口前必须 task(risk-officer)」 |
| 预声明 skill_trace | 仅 `task()` 流事件 | 前端已忽略纯 available 链（`CopilotFinalMeta` OBSERVED 集合）；P0 停发预算 SSE |
| skill_specs.system_prompt | SKILL.md 正文 | 删 Python 里 `_RESEARCHER` 等字符串 |
| SkillRegistry 启停 | `extensions_config.json` | 设置页已写该文件 |
| envelope | SOUL.md + DynamicContext | 见 §4 |
| 按 intent 预取上下文 | 域工具按需 | `get_portfolio_snapshot` 等；页/代码只注入元数据 |
| TurnSummary | checkpoint + 域工具 | 「刚才那张草案」→ `list_rebalance_drafts` |
| SQLite 当模型历史 | checkpoint | SQLite 仅 UI 投影 |
| 按 intent 的 plan_mode | TodoMiddleware 常开或按线程 | 简单问题模型不写 todos |
| token 双闸 | 只留 DeerFlow `token_budget` | 删 envelope 里的 max_subagents 软闸 |
| ResultNormalizer | SKILL.md 输出框架 + SOUL 免责声明 | 前端对缺失 confidence 降级隐藏，不造假数据 |
| A2/A3/A4 | `tool_groups` + 请求 authority | 配置，不是编排 |
| previous_tool_calls 回灌 | SKILL.md「已在历史中的行情勿重拉」 | 修重复调用，不修第二份台账 |

---

## 4. DeerFlow 侧要补的配置（产品纪律）

这些是「只保留 DeerFlow 能力」时，必须写进 harness 配置/技能的内容，而不是 Python。

### 4.1 Lead Agent 指令（SOUL / 系统提示增量）

用 DeerFlow 自定义 agent 或 `deerflow_config` 能注入的系统提示，固定如下语义（文案实施时精炼，不进用户消息）：

- 身份：Stock Agent 个人投研助手；禁止自称 DeerFlow。
- 研究-only：不下真实单；草案须用户在页面确认。
- 简单问题：直接调域工具回答，禁止为查一个 PE 而 `task()`。
- 深度研究：可并行委派 researcher / valuation / catalyst；报告用 report-writer。
- 调仓 / 交易前审查：收口前必须委派 risk-officer，并将其结论写入最终回答。
- 安全：不要求完整持仓明细、不泄露路径/密钥/env。
- 引用：数字必须带来源；降级须说明。
- 免责声明：仅供研究，不构成投资建议（每轮 final 由模型写，不由 Python 补）。

### 4.2 SKILL.md 必须改的三处

1. **所有技能 `description`**：写清「何时该委派我 / 何时 Lead 自己干就行」。例如 researcher：仅在用户要深度研究、多情景、正反方时委派；单指标查询不要委派。
2. **`rebalance-planner`、涉及拟单的技能**：正文增加「收口前必须 `task(risk-officer)`」。这替换 `INTENT_BUDGETS.required_skills`。
3. **Python `system_prompt` 迁入正文**：`skill_specs.py` 里 `_RESEARCHER` 等与 SKILL.md 已部分重复。P2 以 SKILL.md 为准做一次合并（保留反方纪律、市场结构必调、引用格式），然后删除 Python 副本。

`custom_agents.system_prompt` 改为 SKILL.md 全文或「角色+工作流」节，由生成器从 markdown 读取，不再从 `WorkbenchSkill.system_prompt` 读取。

### 4.3 动态上下文（替代 envelope 里的 condensed_*）

只注入元数据，不注入业务快照：

```json
{
  "current_page": "holdings",
  "anchor_symbol": "600519",
  "authority_level": "A4"
}
```

实施选择（按「只走 DeerFlow」优先）：

- **首选**：config 里挂 DynamicContext / 等价的 context 注入（adapter 通过 `configurable` 或官方 client 参数传入上述三字段）。
- **次选**：stream 前用一条极短的、非 JSON envelope 的系统侧说明（仍不是用户消息包装）。若官方 client 没有稳定注入口，才用这条；并在 adapter 注释写明这是权宜，等官方 API。

禁止再使用 `{"envelope_version": "v0.22", ...}` 包住 `user_message`。

上传标记：今天 `_with_turn_upload_files` 靠 `"envelope_version"` 识别 HumanMessage（`deerflow_client.py`）。P0 必须改成「本轮 stream 构造的 HumanMessage 一律打 `additional_kwargs.files`」，否则附件会回退到「分析这个文件」四向澄清。

### 4.4 权限与工具组

保持 `deerflow_config.py` 的 `a2-research` / `a3-risk` / `a4-planner` / `a5-blocked`。  
每轮按会话 `authority_level` 传 `groups`（或等价过滤）。A2 请求不得看到 `generate_draft_order`。这是 DeerFlow 工具组，不是 IntentRouter。

`confirm_rebalance_draft` 继续 denied；确认只走 HTTP。`place_real_order` 继续 denied。

### 4.5 子代理与 plan_mode

- `subagent_enabled=True` 作为 default（可用 env 关掉做对照实验）。
- `plan_mode=True` 作为 default：TodoMiddleware 在复杂任务写 todos；简单任务模型可以不写。若实测闲聊被 todos 污染，改为「仅当本 thread 已有 ≥N 次工具调用或用户消息超长」再开——判断放在 adapter 的 thread 元数据上，**不要**复活 intent 表。

`max_concurrent_subagents` 用 DeerFlow 配置（现有钳制 2–4），不再用 `INTENT_BUDGETS.max_subagents`。

---

## 5. 实施阶段

每阶段可单独合并。后一阶段依赖前一阶段的验收。预估 **1 人 4–6 周**（含回归），不是换底座那种季度级项目。

### P0 — 停预编排（约 3–5 天）

**目的：** 先让简单问题不再被预算清单和 envelope 裹住。验证「Lead 能自己决定零委派」。

代码：

- `copilot_service.stream_run`：不再 yield 预算阶段 `skill_trace`；`subagent_enabled=True`；`plan_mode=True`（或按 §4.5）。
- `render_prompt_envelope`：改为透传 `user_message`；至多附加 §4.3 三字段。
- `_with_turn_upload_files`：去掉对 `envelope_version` 的依赖。
- 前端：预算 SSE 可保留监听（空则无 UI）；`SkillTraceChain` 已要求 OBSERVED，行为应不变。
- 删除 envelope 内 `delegation_budget` / `skill_output_schemas` / `session_state` / `previous_tool_calls` 注入。TurnSummary 本阶段可暂存但不回灌。

测试：

- 改 `tests/test_copilot_final_layer.py`：首事件不再必须是 `skill_trace`。
- 改 `tests/test_api.py` / `test_services.py` 中「预声明 trace 含 report-writer / execution-agent-disabled」类断言 → 改为「无预声明」或「仅 observed」。
- 新增：stub/direct 下「茅台市盈率」类短问题不得出现 `tool=task`（P0 在 stub 里用夹具模拟；真实模型作为手工验收）。
- 修 `test_turn_upload_files_marked_on_envelope_human_message`。

验收：

- [x] 用户消息进 DeerFlow 的 content 不含 `envelope_version`。
- [x] 流式开始没有「本轮可委派谁」的 skill_trace。
- [x] 上传附件后「分析这个文件」不再无故四向澄清（回归 uploads 测试）。
- [x] stub 全量 pytest 绿。
- [ ] 手工：短问题零 `task()`；「全面研究 600519」允许 `task()`。

回滚：恢复 envelope 与预发 skill_trace；git revert P0。

### P1 — 删除 IntentRouter（约 3–5 天）

**目的：** 入口不再按正则贴技能标签。

代码：

- `create_run` 不再调用 `IntentRouter.route`。会话仍有 `page` / `symbol` / `authority_level`，只作为 DynamicContext 与 tool_groups。
- 任务标题改为截断后的用户消息，不再 `Copilot: stock_research`。
- 删除对 `intent.required_authority` 的预检；权限只在工具执行时由 `PermissionGuard` + tool_groups + guardrail 执行（请求档低于工具档 → 工具失败，模型应改口）。
- `tests/test_intent_router.py` 整文件删除或改为 SKILL.md description 契约测试（可选：解析 frontmatter 含触发词，不做运行时路由）。
- `CopilotContextBuilder.build` 去掉 `intent` 分支，只保留 page/symbol 元数据；预取 holdings/risk 停止。

验收：

- [x] 代码库无 `IntentRouter.route` 调用。
- [x] 「买入茅台」不创建 execution run；若模型调 `place_real_order`，guardrail/工具拒绝且用户看到研究-only 说明。
- [x] A2 会话调 `generate_draft_order` 被拒。
- [ ] 个股页锚定 600519 时，短问「现在价多少」不需要用户再打代码（DynamicContext.symbol）。

风险：以前 regex 把「看看我的持仓」打成 risk_review 并预取持仓，现在模型必须自己调 `get_portfolio_snapshot`。若漏调，用 SOUL.md「用户在持仓页问组合时先调快照」修，**不加回路由**。

### P2 — 技能单一属主（约 4–6 天）

**目的：** 删掉 `skill_specs` 里的双份 prompt 与 INTENT_BUDGETS。

代码：

- 合并 Python `system_prompt` → 各 `skills/custom/*/SKILL.md`。
- `subagent_config_dicts()` 只从 SKILL.md 读 description / allowed-tools；`system_prompt` = markdown 正文（或指定节）。
- 删除 `INTENT_BUDGETS`、`intent_budget*`、`subagent_intent_enabled`、`plan_mode_intent_enabled`。
- `SkillRegistry` 缩成读 `extensions_config.json` + SKILL.md 列表；或直接删，启停只走 extensions_store。
- `execution-agent-disabled` 占位行删除；UI 不再展示一条 blocked 执行代理。真下单拒绝靠 guardrail 即可。
- `rebalance-planner/SKILL.md` 写入必跑 risk-officer。
- 更新 `doc/STACK_DECISIONS.md` §1：删除「必须 envelope」「subagent 锁定 False」。
- 更新 `doc/README.md` 原则 6、7、9（skill_trace 改为 observed；prompt 改为原文 + 动态上下文）。

测试：

- 删除 `tests/test_skill_trace.py` 或改成「task 事件能投影为 observed 链」。
- 新增：从 SKILL.md 生成的 `custom_agents` 含 8 个投研技能；`system_prompt` 非空且含「反方」等关键纪律（researcher）。

验收：

- [x] `skill_specs.py` 不再保存长 prompt 字符串。
- [x] 生成 config 的 `subagents.custom_agents` 与 SKILL.md 一致（单测比对 allowed-tools）。
- [ ] 设置页开关技能仍只写 `extensions_config.json`，下一轮生效。

### P3 — 会话单一真相（约 4–6 天）

**目的：** 模型只从 checkpoint + memory + 工具读状态。

代码：

- 停止 `_build_turn_summary` 注入下一轮上下文；可留内存结构给 UI「本轮改了哪些草案」徽章，但不得进模型。
- `copilot_session_state.py`：若仅服务模型，删除；若服务 UI，改名为投影，不叫 session memory。
- DeerFlow memory 保持开启；设置页「AI 记忆」继续打 memory API。
- adapter：投影落库时仍过滤 checkpoint 回放（现有 `historical_msg_ids`）。禁止把 SQLite 历史拼进 `stream(message=)`。
- 文档：`doc/deerflow-conversation-mechanism.md` 更新为「重复调工具用 skill 约束，不用 previous_tool_calls」。

验收：

- [ ] 多轮「刚才那张草案呢」在真实模型下能答到（工具查库），不依赖 TurnSummary。
- [ ] 重启后端后同一 session_id 续聊（checkpoint），UI 列表来自 SQLite 投影且不重复刷旧工具卡。
- [x] 无 `session_state` / `turn_summary` 键进入模型可见消息。

### P4 — 拆薄 CopilotService（约 5–8 天）

**目的：** 文件体积与职责对齐网关。

代码：

- 拆分或压缩 `copilot_service.py`：会话 CRUD、stream 泵、投影、reconnect。编排辅助函数应已在 P0–P3 删光。
- 删除 `result_normalizer.py`；final payload 以模型输出为准。前端对缺字段隐藏板块，不展示假的「信心度 中」。
- stub 模式：不再按 intent 伪造多技能链；stub 直接调 bridge 或返回简短文本，事件形状与 mapper 一致。
- `task_service.skill_trace`：改为 run 结束后的 observed 快照，或删除任务页上的预规划链。
- 回归 `scripts/deerflow_smoke.py`、`scripts/closed_loop_smoke.py`。

验收：

- [x] `copilot_service.py` 不再 import `intent_router` / `skill_specs.INTENT_BUDGETS` / `build_prompt_envelope`。
- [x] `uv run pytest` 全绿；`frontend` vitest 中 copilot 相关绿。
- [ ] 手工黄金路径见 §7。

---

## 6. 测试策略

| 层 | 覆盖 |
|---|---|
| 单元 | SKILL.md 解析与 custom_agents 生成；uploads 标记；guardrail 拒绝名单；tool_groups 随 authority 过滤；mapper 回放过滤 |
| 集成（stub） | 无预声明 skill_trace；create_run 无 intent 字段依赖；投影落库；A2 不能出草案工具 |
| 集成（direct，手工/可选 CI） | 短问零 task；深研有 task；调仓路径出现 risk-officer 委派；澄清卡；多轮草案查询 |
| 前端 | SkillTraceChain 仅 OBSERVED；缺 confidence 不显示假徽章；plan todos 仍渲染 |
| 明确放弃 | `test_intent_router.py` 行为断言；「execution-agent-disabled 出现在 trace 末尾」 |

真实模型用例不进默认 pytest（保持现有 stub 纪律）。P0/P4 各做一次本机 direct 清单，写入 PR 描述。

---

## 7. 黄金路径（每阶段结束必点）

1. 总览闲聊：「你是谁」→ 自称 Stock Agent，不提 DeerFlow。
2. 个股页锚定 600519：「现在市盈率多少」→ 零或一次域工具，无子代理卡。
3. 「全面研究 600519，给正反方」→ 可见 researcher（及可选 valuation/catalyst）task 卡，有反方。
4. 持仓页：「给我调仓草案」→ 有 risk-officer 委派或明确风控结论，草案 pending，页面确认仍走 HTTP。
5. 「买入茅台」→ 不下单，说明研究-only。
6. 上传一段研报 PDF：「摘要要点」→ 读上传文件，不四向澄清。
7. 多轮：出草案后追问「那张草案风险点」→ 能指到草案，不要求用户再贴 ID（工具 list/get）。
8. 设置里关掉 researcher → 深研不再委派该技能。

---

## 8. 风险与预演失败

| 失败 | 表现 | 处理 |
|---|---|---|
| 简单问题仍狂委派 | 查 PE 也拉四个子代理 | 改 SKILL.md description + SOUL「零委派」；加一条可选回归（task 次数）。不加 IntentRouter |
| 调仓漏风控 | 只有 planner 没有 risk-officer | SKILL.md 必跑句 + 抽查黄金路径 4；可在投影层打 metric，**不要**把 required_skills 表加回 Python |
| 持仓页不问组合就答 | 没调 get_portfolio_snapshot | DynamicContext 写明「在 holdings 页先考虑组合工具」 |
| 上传回归 | envelope 标记删除后澄清风暴 | P0 必改 HumanMessage files 标记 |
| 前端仍等首包 skill_trace | 加载态挂起 | 确认 `useCopilotChat` 不依赖首事件类型 |
| stub 测试大面积红 | 夹具假设 intent/trace | 按阶段改测试，禁止为绿测试保留 IntentRouter |
| prompt 变胖 | 常开 subagent + 全部技能 description | DeerFlow 渐进加载只注入 name+description；监控 P0 前后 input tokens |
| STACK_DECISIONS 与代码打架 | 后人又加回 envelope | P2 必须改栈决策文档 |

---

## 9. 文档与栈决策同步（P2 强制）

`doc/STACK_DECISIONS.md` §1 改为：

- 循环仍只走 `DeerFlowClient`，不手写 StateGraph。
- 用户消息原文进 `stream()`；上下文用 DeerFlow 中间件 / 动态配置。
- `subagent_enabled` / `plan_mode` 默认开；用技能描述约束委派，不用 Python 锁定 False。

`doc/README.md` 原则：

- 6：skill_trace 是 observed 委派投影，不是预规划 Team Run。
- 7：默认 embedded/direct；stub 仅测试；子代理是 DeerFlow 原生产品能力。
- 9：禁止把完整持仓/ledger 塞进 prompt；允许 page/symbol/authority 元数据。

本方案实施完成后，`doc/AI_CHAT_ARCHITECTURE.md` / `MULTI_AGENT_CHAT.md` 按目标形态改一版「当前架构」，旧双层图归档为历史。

---

## 10. 工作量与人员

| 阶段 | 人天 | 主要改动面 |
|---|---|---|
| P0 | 3–5 | copilot_service、envelope、uploads、大量测试断言 |
| P1 | 3–5 | intent_router 删除、context builder、权限仅工具时 |
| P2 | 4–6 | SKILL.md 合并、skill_specs 瘦身、栈决策 |
| P3 | 4–6 | session_state、投影纪律、多轮手工 |
| P4 | 5–8 | 拆服务、stub、任务页、smoke |
| 缓冲 | 3–5 | 真实模型回归、token 对比、文档 |

合计约 **4–6 周 / 1 人**。不要与「整仓迁 Pi」的 9–13 个月混为一谈。

建议顺序：P0 单独 PR（可回滚、能验证判断）；P1+P2 可同迭代；P3+P4 同迭代。每个 PR 必须带 §7 对应项的手工记录。

---

## 11. 完成定义

当且仅当同时成立：

1. 模型可见输入中没有 envelope JSON、没有 intent 名、没有预生成技能链、没有 TurnSummary。
2. 编排决策只发生在 DeerFlow（Lead Agent + 技能 + 中间件 + guardrail）。
3. Python Copilot 路径只做 thread、权限档、SSE、投影、上传。
4. §7 八条黄金路径在 direct 模式下通过。
5. `STACK_DECISIONS.md` 与代码一致。
6. 默认 pytest（stub）全绿。

未完成的标志：为了修委派质量又加回一张 Python 意图/预算表。

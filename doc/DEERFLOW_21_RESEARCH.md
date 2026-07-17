# DeerFlow 2.1 深度调研与集成方案

> 2026-07-17。范围:上游 bytedance/deer-flow 最新版调研 + 本地内嵌 `deerflow_harness 2.1.0`
> 全量能力盘点 + 与本系统(Stock Agent)的差距分析与集成优先级。

## 一、版本态势

- **上游公开版**:2.0.0(2026-06-25)。与 1.x(Deep Research 工作流)**完全不同源**的重写:
  「SuperAgent harness」= lead agent + 子代理 + 沙箱 + 记忆 + 技能 + 消息网关。MIT。
- **本地内嵌**:`deerflow_harness 2.1.0`(dist-info,无内嵌 `__version__`)——**领先公开版的
  main 快照**,不落后。Requires-Python ≥3.12,LangChain 1.x / LangGraph 1.x 基座。
- **上游 Unreleased(main)**:可插拔记忆系统(memory 配置面要变!)、SKILL.md 定义为运行时包边界、
  沙箱 Helm ClusterIP 默认、多家 OpenAI 子类 `api_base` 修复。
- **升级注意**:我们经 `DeerFlowClientAdapter` 版权安全边界消费它,升级成本集中在
  config schema(尤其 memory 重构);事件映射(`DeerFlowEventMapper`)按 LangGraph 事件形态,稳定。

## 二、能力全景 × 我们的使用现状

图例:✅ 已在用 · ⚙️ 已启用未深用 · ⬜ 未启用 · 🚫 harness wheel 里没有(需 Gateway server 形态)

| 能力域 | 内容 | 现状 |
|---|---|---|
| 嵌入式客户端 | `DeerFlowClient` 进程内使用,SSE 等价事件流 | ✅ direct/embedded 双模 |
| 子代理 | custom_agents 配置面、并发 3(钳 2-4)、模型继承、内建 general-purpose/bash | ✅ 8 个投研技能子代理 |
| 技能 SKILL.md | 渐进加载(名称+描述进 prompt,激活才读全文)、安全扫描、`/mnt/skills` 挂载 | ✅ skills/custom |
| plan mode | TodoMiddleware:计划清单 + 未完成阻止收口 | ✅ 按 intent 开 |
| 反问澄清 | ClarificationMiddleware + ask_clarification | ✅ |
| MCP | 多服务器(stdio/sse/http)、OAuth 自动刷新、会话池、经 tool_search 延迟加载 | ✅ 设置页可配 |
| tool_search | 延迟工具发现,省 prompt token | ✅ 随 MCP 自动开 |
| 记忆 | memory.json + LLM 事实抽取 + 注入(默认开);设置页「AI 记忆」即此 | ✅ |
| 摘要压缩 | DeerFlowSummarizationMiddleware(保留近期技能读取内容) | ✅ 32k 触发 |
| 循环检测/熔断/工具输出预算 | loop_detection(默认开)、circuit_breaker、tool_output(默认开,大结果落盘换预览) | ✅/⚙️ |
| 护栏 | GuardrailMiddleware + AllowlistProvider(denied: 真实下单) | ✅ |
| 观测 | Langfuse/LangSmith 回调、token_usage 步骤归因 | ⚙️ token_usage 开,Langfuse 未配 |
| 搜索 provider | 14 个社区扩展:tavily/brave/serper/exa/firecrawl/ddg/searxng/jina/browserless/groundroute/**infoquest**/image_search | ⚙️ tavily→serper→ddg 三级择优,中文财经向的 infoquest 未接 |
| **沙箱执行** | Local(host bash 默认禁)/**aio_sandbox Docker**/K8s;bash/glob/grep/write_file/str_replace 工具;路径安全+命令审计 | ⬜ 只开了只读文件工具,bash/写盘未启 |
| **token_budget** | 每 run token 硬预算(软警告+硬停),默认关 | ⬜ |
| vision | ViewImageMiddleware + view_image(模型支持视觉时) | ⬜ |
| present_files | 向用户呈现产出文件 | ⬜ |
| 会话目标 goals | 上游 README 有(`/goal`),**2.1.0 嵌入式 client 无此 API** | 🚫 未到 harness |
| 定时任务 | 上游 Gateway server 的 scheduler;**harness wheel 无 scheduler 模块** | 🚫 |
| IM 双向网关 | WeCom/飞书/Telegram/Slack/钉钉 WebSocket 双向;config/persistence 有 channel_connections,**连接器运行时不在 wheel** | 🚫 |
| 技能自进化 | skill_evolution(代理自改技能),默认关 | ⬜ 观察 |
| ACP 代理 | 调用 ACP 兼容外部代理 | ⬜ 观察 |
| 线程分叉/上下文手动压缩/自更新代理 | 上游 Web UI 侧能力 | 🚫/观察 |
| TUI / LangGraph Server / postgres / OIDC | 部署与多用户面 | 不适用(单用户本地) |

完整 24 中间件链、AppConfig 全字段清单见附录。

## 三、集成方案(按优先级)

### P0 沙箱代码执行——给 AI 一个 Python 工作台 ✅ 已落地(2026-07-17)
投研场景下最大的能力解锁:AI 现在只能调用我们预定义的域工具,开沙箱后可以**写代码算**——
自定义指标、持仓归因、蒙特卡洛压力测试、matplotlib 画图,算完用 `present_files` 呈现。
- 路线:优先 `community/aio_sandbox`(Docker 隔离);无 Docker 时 Local provider + 受控放开
  `bash/write_file/str_replace`(host bash 默认禁,须显式评估)
- 已有的安全基座直接复用:SandboxAudit 命令审计、路径遍历拒绝、Guardrail 白名单、输出上限
- 权限映射:bash/write 归 a3 工具组;委派预算的 authority_cap 天然封顶
- 配套:present_files 产物 → 聊天工具卡 → 右栏详情/下载

### P0.5 启用 token_budget ✅ 已落地(随 P0,run 级 300k 可 env 调)
与我们的 INTENT_BUDGETS 委派预算互补:意图预算管"能拉谁",token_budget 管"这轮最多烧多少"。
`token_budget.enabled + max_tokens`,按 intent 分档(闲聊 50k / 深研 300k)可在 adapter 传参层做。

### P1 定时任务(1-2 天,不依赖 DeerFlow)
harness 里没有 scheduler(Gateway 专属),但我们后端已有 monitor 循环的成熟模式——自建
cron 表(repo + scheduler service)定时 `create_run`(盘前简报/周度复盘/收盘复评)。
这正好解锁功能页规划里缓议的「任务页 = 后台/定时视角」。

### P1 InfoQuest 情报源(0.5 天)
BytePlus 中文向搜索/爬取,对 A 股情报质量优于 ddg/tavily 英文源。挂 `INFOQUEST_API_KEY`
即入 web_search 择优链;catalyst-tracker/researcher 直接受益。

### P2 vision 看图(0.5 天)
确认 mimo-v2.5 视觉能力后开 vision feature:上传 K 线/研报截图让 AI 读图。
上传管道(uploads + markitdown)已通,只差 view_image 环节。

### P2 企微双向对话(2-3 天,自建不引入第二运行时)
上游 IM 网关要跑完整 Gateway server(第二个部署单元 + 它自己的 DB/认证),单用户本地场景过重。
建议**升级现有企微通道为双向**:WebSocket 收消息 → create_run → 结果推回(现有告警推送反向复用)。
DeerFlow 的 channel_connections 配置模型可作为 schema 参考。

### P3 观察项(暂不动)
- **会话目标 goals**:等 harness 嵌入式 API(`client.set_goal`)落地再接——盯盘场景很配
  ("盯到 AAPL 回撤 5% 为止")
- **技能自进化**:AI 自改 SKILL.md,与我们"技能单一属主"治理需先对齐
- **可插拔记忆(上游 Unreleased)**:落地后可把记忆后端换成 SQLite 并与工作区档案合并,
  升级时 memory 配置面要跟着改
- **Langfuse**:自托管后打开 tracing,诊断页可挂 trace 链接

## 四、风险与纪律

1. **版权安全边界不破**:一切新能力仍经 adapter/config 消费,不 import DeerFlow 内部类
   (插件点统一走 `use:` 类路径反射,恰好是配置层能力)。
2. **升级策略**:锁 `deerflow_harness==2.1.0`;升级窗口盯上游 memory 重构与 SKILL.md
   包边界两个 breaking 点;`config_version` 校验会给告警。
3. **沙箱是安全敏感项**:上线顺序 = Docker 隔离 → 审计日志核对 → 再考虑 Local bash;
   guardrails 保持 denied 真实交易类工具。

---

## 附录 A:deerflow_harness 2.1.0 完整能力面(盘点原文)

### 中间件生产链(约 24 个,按装配顺序)
Input(防注入)→ThreadData(线程目录)→Sandbox→Uploads→Dangling(悬空 tool_call 补齐)→
LLMError(重试/熔断)→Guardrail→SandboxAudit→ToolError→DynamicContext(日期/记忆注入,
保持 system prompt 静态利于前缀缓存)→SkillActivation→Summarization→Todo→TokenUsage→
Title→Memory→ViewImage→DeferredToolFilter→SystemCoalescing(多 System 合并,兼容严格后端)→
SubagentLimit→LoopDetection→TokenBudget→SafetyFinishReason→Clarification(恒链尾)

默认开:memory、loop_detection、title、tool_output;默认关:summarization、token_budget、
guardrails、tool_search、skill_evolution。

### AppConfig 顶层字段
log_level / token_usage / token_budget / models / sandbox(必填 use) / tools / tool_groups /
skills / skill_evolution / extensions(MCP+技能状态,独立文件) / tool_output / tool_search /
title / summarization / memory / agents_api / acp_agents / subagents / guardrails /
suggestions / circuit_breaker / channel_connections / loop_detection / safety_finish_reason /
auth / database(memory|sqlite|postgres) / run_events / checkpointer / stream_bridge / config_version。
支持 `$ENV` 解析、mtime+sha256 热重载、ContextVar 运行时覆盖。

### 关键机制
- **插件化基座**:`reflection.resolve_class`——模型/沙箱/技能存储/守卫 provider 全部
  「类路径字符串 → 类」注入
- **多模型**:命名模型表 + 各处(title/summarization/memory/subagent)可指定 model_name;
  provider 适配含 Claude(Code OAuth)/vLLM/MindIE/Codex/DeepSeek/MiMo/MiniMax/StepFun 补丁
- **子代理**:内建 general-purpose(150 turns)与 bash agent(60 turns);并发 3;
  token 归集回主线程
- **沙箱输出上限**:bash 20k / read_file 50k / ls 20k 字符
- **持久化**:run/feedback/thread_meta/user/channel_connections 统一 DB(Alembic 迁移);
  checkpointer 独立(memory/sqlite/postgres)
- **依赖要点**:langchain≥1.2.15、langgraph≥1.1.9、langgraph-api、markitdown[all,xlsx]、
  duckdb、kubernetes、agent-client-protocol(ACP)、tavily/exa/firecrawl SDK;
  extras: postgres/ollama/tui/pymupdf/groundroute

### 主要环境变量
`DEER_FLOW_CONFIG_PATH`、`DEER_FLOW_EXTENSIONS_CONFIG_PATH`、`DEER_FLOW_HOME`、
`DEER_FLOW_SKILLS_PATH`;模型凭证 `CLAUDE_CODE_OAUTH_TOKEN` 等;
社区工具 `TAVILY_API_KEY`/`SERPER_API_KEY`/`INFOQUEST_API_KEY`/`JINA_API_KEY` 等。

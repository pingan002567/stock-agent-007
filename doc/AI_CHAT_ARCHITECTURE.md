# AI Chat 完整架构 —— 多 Agent + 工具深度绑定

> 项目: stock-agent-001 | 日期: 2026-06-06
> 统合: TOOL_IN_DEERFLOW.md + MULTI_AGENT_CHAT.md

---

## 总览

```
用户消息 "全面分析 AAPL"
│
▼
┌─ Layer 1: CopilotService（编排层）────────────────────────────┐
│  intent_router → "stock_research"                              │
│  permission_guard → A2 通过                                     │
│  context_builder → 上下文卡 {symbol, holdings, risks}          │
│  prompt_envelope → JSON 包装                                    │
│                                                                 │
│  决策: intent 是简单还是复杂?                                    │
│    简单 → subagent_enabled=False (Lead Agent 单打)              │
│    复杂 → subagent_enabled=True  (Lead + Subagents 并行)        │
└────────────────────────────────────────────────────────────────┘
│
▼
┌─ Layer 2: DeerFlowClientAdapter（适配层）──────────────────────┐
│  set_bridge(tool_bridge)     ← ContextVar 注入                 │
│  client.stream(envelope)     ← 启动 LangGraph 图                │
└────────────────────────────────────────────────────────────────┘
│
▼
┌─ Layer 3: DeerFlow Agent（执行层）─────────────────────────────┐
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Middleware Chain（18 个中间件，按序执行）                     │ │
│  │                                                             │ │
│  │ ★ GuardrailMiddleware  ← 工具预授权（deny place_real_order）│ │
│  │ ★ ToolErrorHandling    ← 工具异常 → ToolMessage（不中断）    │ │
│  │ ★ LLMErrorHandling     ← API 重试(3次) + 熔断器             │ │
│  │ ★ LoopDetection        ← 防死循环                            │ │
│  │ ★ Summarization        ← 长对话自动压缩                      │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Lead Agent（协调者）                                           │
│  │                                                              │
│  ├── 简单模式: 直接调用工具                                      │
│  │   get_stock_context("AAPL") → 结果                           │
│  │   LLM 生成分析文本 → 返回                                     │
│  │                                                              │
│  └── 复杂模式: task() 调度 Subagent                             │
│      │                                                          │
│      ├── Subagent "stock-researcher"                            │
│      │   tools: [get_stock_context, get_daily_history,          │
│      │           search_stock_intel]                             │
│      │   → 返回 {基本面, 技术面, 情报}                           │
│      │                                                          │
│      ├── Subagent "risk-officer"                                │
│      │   tools: [get_portfolio_snapshot, evaluate_policy_risk]   │
│      │   → 返回 {集中度, 行业风险}                                │
│      │                                                          │
│      └── Lead Agent 汇总 → 生成最终报告                          │
└────────────────────────────────────────────────────────────────┘
│
▼
┌─ Layer 4: Tool Execution（工具执行层）─────────────────────────┐
│                                                                 │
│  StructuredTool._run()  ← DeerFlow 内部执行（唯一入口）          │
│  │                                                              │
│  ├── 1. Pydantic 校验  args_schema(**kwargs)                   │
│  ├── 2. ContextVar 获取 bridge = _bridge_ctx.get()              │
│  ├── 3. ExecutionPolicy.decide(name) → blocked/allowed          │
│  ├── 4. PermissionGuard.require(authority) → A2/A3/A4 检查      │
│  ├── 5. 业务执行    bridge._handlers[name](args)                │
│  ├── 6. ledger 写入  bridge._record_execution()                 │
│  └── 7. 返回 JSON   json.dumps(result)                         │
│                                                                 │
│  ★ adapter 不拦截重复执行（_map_and_execute_tools 已删除）       │
│  ★ 每个 tool_call 只产生 1 条 tool_execution 记录                │
└────────────────────────────────────────────────────────────────┘
│
▼
┌─ Layer 5: Event Pipeline（事件管道）───────────────────────────┐
│                                                                 │
│  DeerFlow StreamEvent  →  mapper.map()  →  Workbench dict       │
│  │                                                              │
│  messages-tuple(type=ai, content=delta)  →  partial_answer      │
│  messages-tuple(type=ai, tool_calls=[...]) →  tool_call         │
│  messages-tuple(type=tool, content=result)  →  tool_result      │
│  values {title, messages, artifacts}         →  reasoning       │
│  end {usage}                                 →  final            │
│                                                                 │
│  ★ adapter 只做格式转换 + 别名映射，不拦截执行                    │
└────────────────────────────────────────────────────────────────┘
│
▼
┌─ Layer 6: CopilotService 收口 ─────────────────────────────────┐
│  final 增强: + evidence_refs + next_actions + disclaimer        │
│  事件持久化: CopilotMessage → SQLite                             │
│  SSE 推送:   event → encode_sse() → 前端渲染                     │
└────────────────────────────────────────────────────────────────┘
```

---

## 工具执行流（一次执行，不再双写）

```
改造前：DeerFlow 执行1次 + adapter 拦截再执行1次 → 双写 ledger

改造后：DeerFlow 内部执行（全流程）→ adapter 纯透传

  StructuredTool._run()
    ├── Pydantic 校验      ← LangChain 自动
    ├── ExecutionPolicy     ← blocked? needs_confirmation?
    ├── PermissionGuard     ← A2/A3/A4 权限
    ├── bridge._handlers    ← 业务逻辑
    ├── bridge._record      ← ledger（1条）
    └── return json.dumps() ← LLM 可解析的 JSON
```

## 多 Agent 调度（简单 vs 复杂）

```
简单 intent (stock_research):
  Lead Agent 直接调用工具 → 返回分析

复杂 intent (rebalance_plan):
  Lead Agent 调用 task("stock-researcher") → Subagent 1
  Lead Agent 调用 task("risk-officer")     → Subagent 2
  Lead Agent 调用 task("strategy-analyst") → Subagent 3
  → 最多3个并行 → 各自完成 → Lead 汇总

Subagent 安全边界:
  工具白名单（不进 A4/A5 工具）
  + ExecutionPolicy（blocked 工具拒绝执行）
  + PermissionGuard（权限不足拒绝）
```

## 错误处理三层

```
LLM API 异常 → LLMErrorHandlingMiddleware
  ├── 重试 3 次 + 指数退避
  ├── Circuit Breaker（连续5次失败 → 熔断60s）
  └── auth/quota 错误 → 友好提示

工具执行异常 → ToolErrorHandlingMiddleware
  ├── 捕获 → ToolMessage("Error: xxx...")
  └── Agent 看到错误 → 换方案 → 流程不中断

adapter 兜底 → deerflow_client.py
  ├── stream 启动前异常 → stub 回退
  └── stream 启动后异常 → error + final（不再回退）
```

## 文件索引

| 文件 | 覆盖主题 |
|------|---------|
| `ARCHITECTURE_ANALYSIS.md` | DeerFlow 2.0 总体架构 |
| `CLIENT_SDK_ARCHITECTURE.md` | DeerFlowClient SDK 模块 |
| `AI_CHAT_SDK_INTEGRATION.md` | 当前 Chat 集成分析 |
| `DEERFLOW_FEATURE_PLAN.md` | 特性三阶段规划 |
| `TOOL_DEEP_BINDING.md` | 工具绑定问题诊断 |
| `TOOL_DEEP_BINDING_IMPL.md` | 深度绑定实施指南 |
| `TOOL_IN_DEERFLOW.md` | 工具执行完全交给 DeerFlow |
| `MULTI_AGENT_CHAT.md` | 多 Agent 管理方案 |
| `AI_CHAT_ARCHITECTURE.md` | ★ 本文档：统一架构总览 |

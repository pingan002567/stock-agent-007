# 基于 DeerFlowClient SDK 构建 AI Chat 方案

> 项目: stock-agent-001 | 分析日期: 2026-06-06

---

## 1. 现有架构概览

stock-agent-001 已经完成了一个相当成熟的 AI Chat 集成，架构如下：

```
┌──────────────────────────────────────────────────────────────┐
│                      前端 (React + Vite)                      │
│   /demo → Chat 侧边栏: 会话列表、上下文卡、工具过程卡、结果卡    │
└──────────────────────────┬───────────────────────────────────┘
                           │ POST /api/copilot/stream/{run_id} (SSE)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   FastAPI routes_copilot.py                    │
│   POST /api/copilot/sessions  →  CopilotService               │
│   POST /api/copilot/sessions/{id}/messages → 创建 run + 流式   │
│   GET  /api/copilot/stream/{run_id} → SSE 实时推送             │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    CopilotService (1228+ 行)                   │
│   create_run()  →  意图路由 + 权限检查 + Skill Trace           │
│   stream_run()  →  DeerFlow Adapter → SSE 事件                │
│   Session 管理  →  CopilotSession / CopilotMessage 持久化      │
│   Turn Summary  →  多轮状态追踪 (drafts/reviews/reports)       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│             DeerFlowClientAdapter (1140 行)                    │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  from_env()  ← 三种模式初始化                              │ │
│  │  ├── direct   : 自动生成 config + SqliteSaver + DFC()     │ │
│  │  ├── embedded : import deerflow.client.DeerFlowClient     │ │
│  │  └── stub     : 本地降级（离线可用）                        │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  stream()  ← 核心流式入口                                  │ │
│  │  ├── Prompt Envelope 包装 (render_prompt_envelope)        │ │
│  │  ├── client.stream(envelope_message, thread_id=session_id) │ │
│  │  ├── 同步 Generator → 异步桥接 (asyncio.Queue + 后台线程)   │ │
│  │  ├── DeerFlowEventMapper 事件映射                          │ │
│  │  └── WorkbenchToolBridge 工具拦截执行                       │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────┬───────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
     ┌────────────┐ ┌───────────┐ ┌──────────────┐
     │ EventMapper│ │ToolBridge │ │ PromptEnvelope│
     │ StreamEvent│ │ 14 个工具  │ │ 上下文注入     │
     │ → SSE 事件  │ │ 本地执行   │ │ 权限边界      │
     └────────────┘ └───────────┘ └──────────────┘
```

---

## 2. 核心链路分析

### 2.1 初始化链路 (from_env)

```
from_env(runtime_config)
│
├── 1. API Key 解析
│   └── OPENAI_API_KEY > WORKBENCH_AI_API_KEY > runtime_config.api_key
│
├── 2. 模式选择
│   ├── WORKBENCH_AI_MODE=direct   → _try_direct()
│   ├── WORKBENCH_DEERFLOW_MODE=embedded (默认)
│   │   ├── 有 API Key → 自动升级到 direct
│   │   └── 无 API Key → 尝试 import deerflow.client
│   └── 其他 → stub (离线降级)
│
├── 3. _try_direct() — 自给自足模式
│   ├── generate_config() 生成临时 config.yaml
│   │   └── 写入 model_name / api_key / base_url / sandbox
│   ├── 设置 DEER_FLOW_CONFIG_PATH 环境变量
│   ├── 创建 SqliteSaver (SQLite checkpointer)
│   └── DeerFlowClient(config_path, checkpointer, model_name, ...)
│
├── 4. _try_embedded() — 传统嵌入模式
│   ├── importlib.import_module("deerflow.client")
│   └── client_cls(config_path, model_name, ...)
│       └── 无 checkpointer → 每次 stateless
│
└── 5. 返回 Adapter
    └── AgentRuntimeStatus { mode, available, degraded, model_name, ... }
```

**关键设计决策**：
- `direct` 模式自动生成临时 config + SQLite checkpointer，用户只需提供 API Key
- `embedded` 模式不传 checkpointer → 每次调用 stateless（session_id 无效）
- `stub` 模式是离线降级，用于没有 API Key 时的本地演示

### 2.2 流式调用链路 (stream)

```
CopilotService.stream_run(run_id)
│
├── 1. 恢复检查
│   ├── 已持久化的 final_answer → 直接回放
│   └── 已有部分事件但无 final → 返回 error + final（不回放）
│
├── 2. 构建上下文
│   └── copilot_context_builder.build(page, symbol, intent)
│       └── 精简上下文卡（不含 secret/完整持仓/完整历史）
│
├── 3. DeerFlowClientAdapter.stream()
│   │
│   ├── 3a. Prompt Envelope 包装
│   │   └── render_prompt_envelope(user_message, skill_trace, context)
│   │       └── JSON 格式: { user_message, skill_trace, context, safety_constraints }
│   │
│   ├── 3b. 调用 DeerFlowClient.stream()
│   │   └── client.stream(
│   │           message=envelope_message,
│   │           thread_id=session_id or run_id,
│   │           model_name=..., thinking_enabled=True,
│   │           subagent_enabled=False, plan_mode=False
│   │       )
│   │
│   ├── 3c. 同步→异步桥接 (_bridge_sync_stream)
│   │   └── 后台线程消费 Generator → asyncio.Queue → async for 消费
│   │       └── 队列大小: SYNC_STREAM_QUEUE_MAXSIZE = 64
│   │
│   ├── 3d. 事件映射 (DeerFlowEventMapper)
│   │   └── StreamEvent → Workbench 事件:
│   │       ├── messages-tuple(ai, content) → partial_answer
│   │       ├── messages-tuple(ai, tool_calls) → tool_call
│   │       ├── messages-tuple(tool, content) → tool_result
│   │       ├── values → reasoning (状态快照)
│   │       └── end → final (含 usage metadata)
│   │
│   └── 3e. 工具拦截 (_map_and_execute_tools)
│       └── tool_call 事件 → 查询 WorkbenchToolBridge.has_tool()
│           ├── 已知工具 → tool_bridge.execute() → 本地执行 → tool_result
│           └── 未知 DeerFlow 工具 → 透传 SSE，不写本地 ledger
│
├── 4. 事件序列化
│   └── SSEEvent { type, payload } → encode_sse() → SSE 文本
│
└── 5. 收口处理
    ├── final 事件 → normalize_final() + 附加 draft/review/report 元数据
    ├── error 事件 → 分类 (auth_error/rate_limit/timeout/tool_error)
    └── TurnSummary → 更新 session_state（多轮状态追踪）
```

### 2.3 事件类型映射

```
DeerFlow StreamEvent          →  Workbench SSEEvent
─────────────────────────────────────────────────────
messages-tuple(type=ai, content=delta)
    → partial_answer { text: delta }

messages-tuple(type=ai, tool_calls=[...])
    → tool_call { tool, call_id, arguments }

messages-tuple(type=tool, name=xx, content=result)
    → tool_result { call_id, tool, result }

values { title, messages, artifacts }
    → reasoning { phase: "values", latest_text }

end { usage: {input_tokens, output_tokens, total_tokens} }
    → final { conclusion, confidence, usage }

custom { ... }
    → reasoning { phase: "custom", data }
```

---

## 3. 关键模块职责

### 3.1 DeerFlowClientAdapter (agent_runtime/deerflow_client.py)

| 职责 | 实现 |
|------|------|
| 三种模式初始化 | `from_env()` — direct / embedded / stub |
| 同步流桥接 | `_bridge_sync_stream()` — 后台线程 + asyncio.Queue(64) |
| 事件映射 | `DeerFlowEventMapper` — StreamEvent → Workbench dict |
| 工具拦截执行 | `_map_and_execute_tools()` — 已知工具本地执行，未知工具透传 |
| 降级处理 | stub 模式 + stream 启动失败 → stub fallback |
| 工具别名映射 | `strategy_backtest → run_strategy_backtest` 等 |
| 连接测试 | `test_connection()` — httpx 直连 OpenAI 兼容 API 验证 |

### 3.2 CopilotService (app_services/copilot_service.py)

| 职责 | 实现 |
|------|------|
| 会话 CRUD | `list_sessions / create_session / update_session / delete_session` |
| 消息持久化 | `CopilotMessage` → SQLite `copilot_message` 表 |
| Run 创建 | `create_run()` — 意图路由 + 权限 + Skill Trace |
| 流式编排 | `stream_run()` — 恢复/新建 + 事件分发 + 收口 |
| 多轮状态 | `SessionStateData` — drafts/reviews 跨轮追踪 |
| 结果增强 | `normalize_final()` — 附加 draft_id/review_id/report_id |
| 成本估算 | `_estimate_cost()` — 按模型单价计算 |
| 流恢复保护 | 已有部分事件但无 final → 直接 error + final，不重放 |

### 3.3 WorkbenchToolBridge (agent_runtime/tool_bridge.py)

14 个注册工具，按权限分级：

| 权限 | 工具 |
|------|------|
| A2 (研究) | `get_stock_context`, `get_daily_history`, `search_stock_intel`, `get_portfolio_snapshot`, `list_strategies`, `get_backtest_result`, `get_monitor_events`, `get_monitor_rules`, `evaluate_monitor_rules`, `generate_report`, `list_report_templates`, `get_report_quality` |
| A3 (组合/风险) | `get_active_risk_policy`, `list_risk_policies`, `evaluate_policy_risk`, `analyze_portfolio_risk`, `run_strategy_backtest`, `get_paper_portfolio`, `analyze_paper_performance`, `create_paper_portfolio_snapshot`, `list_decision_journal`, `get_decision_journal_entry`, `summarize_decision_outcomes`, `list_review_inbox`, `summarize_review_inbox` |
| A4 (拟单) | `generate_draft_order`, `list_rebalance_drafts`, `get_rebalance_draft`, `create_pre_trade_review`, `list_pre_trade_reviews`, `list_paper_orders` |
| A5 (阻塞) | `place_real_order` — 永久 blocked |

### 3.4 Prompt Envelope (agent_runtime/prompt_envelope.py)

将用户消息包装成 JSON 格式的 envelope：

```json
{
  "user_message": "帮我分析 AAPL",
  "skill_trace": [
    {"step": 1, "skill": "stock-researcher", "label": "股票研究员", "tools": [...], "status": "planned"},
    {"step": 2, "skill": "report-writer", "label": "报告撰写", "tools": [...], "status": "planned"}
  ],
  "context": {
    "page": "stock_detail",
    "symbol": "AAPL",
    "authority_level": "A2",
    "stock_summary": { ... 精简摘要 },
    "holdings_brief": { ... 精简持仓 }
  },
  "safety_constraints": {
    "auto_trade": false,
    "research_only": true,
    "real_order_blocked": true
  }
}
```

**设计原则**：不透传 secret、环境变量、完整持仓、完整 watchlist、完整历史、完整报告 Markdown。

---

## 4. 持久化架构

### 4.1 会话与消息

```
copilot_session
├── session_id (PK)
├── title              ← 自动生成或用户指定
├── current_page       ← 当前所在页面
├── anchor_symbol      ← 锚定股票
├── authority_level    ← 权限等级
├── created_at / updated_at / last_message_at

copilot_message
├── message_id (PK)
├── session_id (FK)    → copilot_session
├── role               ← user / assistant / system / tool
├── kind               ← user_message / tool_call / tool_result / partial_answer / final_answer / ...
├── text               ← 摘要文本
├── page / symbol      ← 上下文
├── run_id / task_id   ← 关联运行
├── payload (JSON)     ← 完整事件数据
└── created_at
```

### 4.2 运行日志

```
copilot_run_log
├── run_id / session_id / task_id
├── mode / active_client / model_name
├── status              ← running / completed / failed
├── tool_call_count
├── usage_input_tokens / usage_output_tokens
├── error_category / runtime_error
├── latency_ms
├── started_at / completed_at
└── payload
```

---

## 5. 流恢复与容错机制

```
stream_run(run_id)
│
├── 已持久化 final_answer?
│   └── YES → 直接回放所有已持久化事件（幂等）
│
├── 已有部分事件但无 final?
│   └── YES → error + final（不回放，避免重复创建报告/草案/审查/snapshot）
│       └── 原因: 部分事件可能已经执行了工具但未持久化结果
│
├── 无持久化消息?
│   └── 从 _runs 内存缓存恢复 或 _recover_run_state() 从数据库重建
│
└── 新建 run
    └── 正常流式执行
```

**容错策略**：
- `stream()` 启动前异常 → 自动回退到 stub
- `stream()` 启动后异常 → 输出 error + final，不回退 stub（避免答案不一致）
- `_ToolExecutionTerminalError` → 特殊错误流：leading_events(已产出) + error + final
- 未知 DeerFlow 工具 → 透传 SSE，不写 ledger，不阻断流

---

## 6. 当前约束与边界

| 约束 | 说明 |
|------|------|
| V1 固定 `subagent_enabled=false` | 不暴露 DeerFlow 子智能体为产品 TeamRun |
| V1 固定 `plan_mode=false` | 不使用 DeerFlow Todo 中间件 |
| `auto_trade=false` | 所有调仓输出标记为研究性质 |
| `research_only=true` | Copilot 只做研究结论与拟单草案 |
| `place_real_order` blocked | A5 权限永远阻断 |
| Paper order 只由 HTTP/UI 创建 | ToolBridge 不暴露 `create_paper_order` |
| Skill-symbol 关键词匹配 | stub 模式根据消息关键词判断工具 |
| Prompt envelope 精简 | 不传 secret/完整持仓/完整历史 |
| 线程桥接 | 同步 Generator → asyncio.Queue(64) 后台线程 |

---

## 7. 你的项目已有的优势

1. **完整的 Adapter 层**：三种模式（direct/embedded/stub）自动降级，用户只需提供 API Key
2. **完善的工具桥**：14 个领域工具，权限分级（A2-A5），内置 stub 回退逻辑
3. **会话持久化**：CopilotSession + CopilotMessage 完整 schema
4. **多轮状态追踪**：SessionStateData 跨轮追踪 drafts/reviews
5. **流恢复保护**：部分输出不回放，避免重复副作用
6. **成本估算**：按模型价格自动计费
7. **连接测试**：httpx 直连 API 验证，无需经过 DeerFlow
8. **Prompt Envelope**：安全精简的上下文注入
9. **前端展示**：会话列表、上下文卡、工具过程卡、结果卡、Next Actions

---

## 8. 可改进方向

| 方向 | 当前状态 | 建议 |
|------|---------|------|
| **多轮对话** | embedded 模式无 checkpointer | 统一使用 direct 模式的 SQLite checkpointer |
| **stream title** | 无自动标题 | direct 模式下可利用 DeerFlow 内置 TitleMiddleware |
| **上下文长度** | 无限制 | 可启用 DeerFlow 的 summarization 中间件 |
| **直接 LLM 调用** | stub 模式走工具 | direct 模式可让 LLM 自由选择工具，不再受 skill-keyword 匹配限制 |
| **Token 统计** | 仅收集 usage | 可开启 `token_usage.enabled: true` 启用完整统计 |
| **流式 title 更新** | 无 | values 事件的 title 字段可用于实时更新对话标题 |
| **Skills 渐进加载** | 未使用 | direct 模式下可配置 available_skills 白名单 |
| **MCP 工具扩展** | 未使用 | 可通过 `update_mcp_config()` 动态添加 MCP 服务器 |

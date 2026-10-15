# AI Chat 深度使用 DeerFlow 特性规划

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 总览：DeerFlow 特性矩阵

DeerFlow 提供了 12+ 个内置特性，当前项目只用了最基础的 `stream()` 调用。以下是按价值和实施复杂度分三阶段的规划：

| 阶段 | 特性 | 价值 | 当前状态 |
|------|------|------|---------|
| P1 | 多轮对话 (Checkpointer) | ⭐⭐⭐⭐⭐ | thread_id 传错，形同虚设 |
| P1 | 自动标题 (TitleMiddleware) | ⭐⭐⭐⭐ | 未启用 |
| P1 | Token 用量追踪 | ⭐⭐⭐ | 基础收集，未用 DeerFlow 原生 |
| P1 | Prompt 前缀缓存 | ⭐⭐⭐⭐ | 静态 prompt 已实现 |
| P2 | 上下文摘要 (Summarization) | ⭐⭐⭐⭐⭐ | 未配置 |
| P2 | 工具循环检测 (LoopDetection) | ⭐⭐⭐⭐ | 未配置 |
| P2 | 技能渐进加载 (Skills) | ⭐⭐⭐⭐ | 未使用 |
| P2 | 工具延迟加载 (Tool Search) | ⭐⭐⭐ | 未启用 |
| P3 | 跨会话记忆 (Memory) | ⭐⭐⭐⭐⭐ | 未使用 |
| P3 | 子智能体委派 (Subagents) | ⭐⭐⭐⭐ | V1 固定 disabled |
| P3 | 熔断器 (Circuit Breaker) | ⭐⭐⭐ | 未配置 |
| P3 | 安全护栏 (Guardrails) | ⭐⭐⭐ | 未配置 |

---

## Phase 1：快速收益（低风险，立即可做）

### 1.1 多轮对话 —— 修复 thread_id

**现状**：`thread_id=session_id or run_id`，但 `session_id` 传的是 `None`，实际用 `run_id`（每次新建）。

**修复**：

```python
# copilot_service.py L498 — 改一行
self.deerflow.stream(..., session_id=state.session_id)  # 原来是 None

# deerflow_client.py L523 — 不用改，自动生效
thread_id=session_id or run_id  # 现在 session_id 有值了
```

**效果**：同一 session 内的多轮对话，LLM 能看到完整历史上下文。用户说"上次那个 AAPL 分析，再补充一下估值"时，Agent 知道"上次"指的是什么。

**注意事项**：
- 必须配置 summarization（见 P2），否则长对话打爆 context window
- embedded 模式需补 checkpointer

### 1.2 自动标题 —— 启用 TitleMiddleware

**现状**：`_derive_title()` 手写规则 → `"AAPL 会话"`，不够智能。

**改造**：

```python
# deerflow_config.py — _build_config() 添加
config = {
    "models": [...],
    "tools": [...],
    "title": {
        "enabled": True,
        "max_words": 8,
        "max_chars": 40,
        "model_name": None,  # 用默认模型
    },
    ...
}
```

**效果**：首次对话后 DeerFlow 自动生成语义标题，如 `"AAPL 估值分析与持仓建议"`。`values` 事件中的 `title` 字段实时更新前端会话列表。

**前端适配**：SSE 监听 `values` 事件 → `event.data.title` → 更新会话列表标题。

### 1.3 Token 用量追踪

**现状**：`end` 事件收集了 `usage`，但未启用 DeerFlow 原生的完整追踪。

**改造**：

```python
# deerflow_config.py — 添加
"token_usage": {"enabled": True}
```

**效果**：
- 每次 tool_call / LLM 调用都记录独立用量
- `TokenUsageMiddleware` 自动注入
- 前端可展示每个工具调用的 token 消耗明细

### 1.4 Prompt 前缀缓存

**现状**：已通过 `DynamicContextMiddleware` 把日期/记忆注入到 `HumanMessage` 而非 `SystemMessage`，让静态部分可被 LLM 提供商缓存。

**确认项**：确保 `config.yaml` 的 `models` 段支持 `supports_thinking` / `supports_vision` 等元数据正确配置，以最大化缓存命中率。

---

## Phase 2：上下文管理（中等投入）

### 2.1 上下文摘要 —— SummarizationMiddleware

**需求**：多轮对话 + checkpointer 会累积消息历史，50 轮后可能超过 100K tokens，必须压缩。

**配置**：

```python
# deerflow_config.py
"summarization": {
    "enabled": True,
    "model_name": None,       # 用轻量模型如 gpt-4o-mini
    "trigger": [
        {"type": "tokens", "value": 32000},   # 32K token 时触发
        {"type": "messages", "value": 40},     # 或 40 条消息
    ],
    "keep": {
        "type": "messages",
        "value": 10,           # 保留最近 10 条
    },
    "preserve_recent_skill_count": 5,          # 保留最近 5 个技能
}
```

**效果**：
- 接近 32K tokens 时自动压缩历史 → 精简摘要
- 保留最近 10 条消息完整上下文
- 最近加载的技能文件不被压缩

**注意**：需要一个 LLM 调用做摘要（消耗 token），推荐用 `gpt-4o-mini`（成本低）。

### 2.2 工具循环检测 —— LoopDetectionMiddleware

**需求**：Agent 可能陷入重复调用同一个工具的循环（如反复搜索同一只股票）。

**配置**：

```python
"loop_detection": {
    "enabled": True,
    "warn_threshold": 3,       # 3 次同类工具调用 → 警告
    "hard_limit": 5,           # 5 次 → 强制中断
    "window_size": 20,         # 最近 20 步窗口
    "tool_freq_warn": 30,      # 30 次总工具调用 → 警告
    "tool_freq_hard_limit": 50,
    # 股票分析场景中，web_search 可能高频使用，适度放宽
    "tool_freq_overrides": {
        "search_stock_intel": {"warn": 40, "hard_limit": 60},
        "get_stock_context":  {"warn": 40, "hard_limit": 60},
    },
}
```

**效果**：防止 Agent 陷入死循环，保护 token 消耗。

### 2.3 技能渐进加载

**需求**：股票分析有不同的分析模式（深度研究、策略回测、风险审查），一次性加载所有技能浪费上下文。

**方案**：不定义 DeerFlow 技能（那是给通用 Agent 用的），而是利用 `available_skills` 白名单，根据 Copilot 的 `intent` 动态选择：

```python
# copilot_service.py — stream_run() 中
INTENT_SKILLS_MAP = {
    "stock_research":        {"stock-researcher", "report-writer"},
    "strategy_backtest":     {"strategy-analyst", "report-writer"},
    "rebalance_plan":        {"stock-researcher", "risk-officer", "rebalance-planner"},
    "risk_review":           {"risk-officer", "report-writer"},
    "monitor_event":         {"stock-monitor", "report-writer"},
}

# 重建 client 时传入
client = DeerFlowClient(
    ...,
    available_skills=INTENT_SKILLS_MAP.get(intent_name, {"stock-researcher"}),
)
```

但这要求每次切换 intent 时重建 Client（`reset_agent()`），有成本。更实用的做法：

**实用方案**：按 session 粒度设置，而非每次 intent：

```python
# 初始化时一次性设置该 session 可能用到的技能
client = DeerFlowClient(available_skills={
    "stock-researcher", "risk-officer", "strategy-analyst",
    "rebalance-planner", "stock-monitor", "report-writer",
})
```

### 2.4 工具延迟加载 (Tool Search)

**现状**：38 个 Workbench 工具全量绑定到模型，每个工具的 schema 都占 token。

**配置**：

```python
"tool_search": {"enabled": True}
```

**效果**：MCP 工具不直接绑定到模型 → 只注入工具名列表 → Agent 通过 `tool_search` 按需激活 → 节省初始 token。

**适用条件**：当 Workbench 工具超过 20 个时收益明显。当前 38 个工具已值得启用。

---

## Phase 3：高级特性（高投入，高价值）

### 3.1 跨会话记忆 —— Memory System

**需求**：用户在不同 session 中反复提到的偏好、关注股票、风险偏好应该被记住。

**配置**：

```python
# deerflow_config.py
"memory": {
    "enabled": True,
    "storage_path": "data/deerflow_memory.json",
    "debounce_seconds": 30,
    "model_name": "gpt-4o-mini",         # 记忆提取用轻量模型
    "max_facts": 100,
    "fact_confidence_threshold": 0.7,
    "injection_enabled": True,
    "max_injection_tokens": 1500,
}
```

**效果**：
- 对话完成后自动提取事实（如"用户关注 AAPL、腾讯"、"偏好保守型策略"）
- 下次对话时自动注入到系统提示词
- 用户说"和上次一样分析"时，Agent 知道"上次"是哪种分析

**与 Copilot Session 的关系**：
- DeerFlow Memory：LLM 自动提取的偏好/风格/知识
- Copilot Session：UI 层的结构化状态（drafts/reviews/reports）
- 两者互补，不冲突

### 3.2 子智能体委派 —— Subagents

**需求**：复杂任务如"全面分析 AAPL 并生成策略建议"可以并行处理：
- Subagent 1：基本面与技术面分析
- Subagent 2：行业对比分析
- Subagent 3：风险策略评估
- Lead Agent：汇总生成最终报告

**改造**：

```python
# 条件启用
client = DeerFlowClient(
    subagent_enabled=True,
    plan_mode=False,
)

# 子智能体配置
"subagents": {
    "timeout_seconds": 900,
    "agents": {
        "general-purpose": {
            "timeout_seconds": 600,
            "max_turns": 80,
        },
    },
}
```

**风险控制**：
- 子智能体不能绕过权限：`place_real_order` 在 tool_bridge 层 blocked
- A5 工具对所有子智能体同样不可用
- 子智能体的 tool_execution 也会写 ledger

**适用场景**：
- 多维度股票分析（基本面 + 技术面 + 行业）
- 批量策略回测（多个策略并行）
- 复杂报告生成（分章节并行撰写）

### 3.3 熔断器 —— Circuit Breaker

**需求**：当 LLM API 连续失败时，快速失败而非不断重试。

**配置**：

```python
"circuit_breaker": {
    "failure_threshold": 5,
    "recovery_timeout_sec": 60,
}
```

**效果**：连续 5 次 LLM 调用失败 → 熔断 60 秒 → 前端显示"AI 服务暂时不可用"。

### 3.4 安全护栏 —— Guardrails

**需求**：对敏感工具调用做预授权检查。

**配置**：

```python
"guardrails": {
    "enabled": True,
    "provider": {
        "use": "deerflow.guardrails.builtin:AllowlistProvider",
        "config": {
            "denied_tools": [
                "place_real_order",
                "upsert_holding",       # 不让 AI 直接改持仓
                "confirm_rebalance_draft",  # 确认草案必须人工
            ],
        },
    },
}
```

**效果**：即使 LLM 尝试调用被禁工具，Guardrails 层也会拦截并返回拒绝原因，不依赖 LLM 自觉。

---

## 实施路线图

```
Phase 1 (本周)                     Phase 2 (下周)                  Phase 3 (本月)
┌──────────────────┐    ┌──────────────────────────┐    ┌──────────────────────────┐
│ 1.1 多轮对话     │    │ 2.1 上下文摘要             │    │ 3.1 跨会话记忆            │
│    修复 thread_id│───▶│    32K token 自动压缩       │───▶│    偏好/风格/关注股票持久化 │
│                  │    │                          │    │                          │
│ 1.2 自动标题     │    │ 2.2 工具循环检测            │    │ 3.2 子智能体委派           │
│    TitleMiddleware│   │    防死循环                 │    │    复杂分析并行化          │
│                  │    │                          │    │                          │
│ 1.3 Token 追踪   │    │ 2.3 技能渐进加载            │    │ 3.3 Circuit Breaker       │
│    完整用量统计   │    │    按分析模式筛选工具        │    │    API 故障快速失败         │
│                  │    │                          │    │                          │
│ 1.4 前缀缓存确认  │    │ 2.4 工具延迟加载            │    │ 3.4 Guardrails             │
│    token 优化    │    │    38 工具按需激活           │    │    工具预授权              │
└──────────────────┘    └──────────────────────────┘    └──────────────────────────┘
```

## 配置集成：最终 config.yaml 模板

```yaml
# 完整的 DeerFlow 配置（在 deerflow_config.py 中动态生成）
models:
  - name: gpt-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    openai_api_key: $OPENAI_API_KEY
    supports_thinking: false
    supports_vision: true

sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false

tools:
  - name: get_stock_context
    group: workbench
    use: backend.agent_runtime.tools:get_stock_context
  # ... 其余 37 个工具

# ------ Phase 1 ------
token_usage:
  enabled: true

title:
  enabled: true
  max_words: 8

# ------ Phase 2 ------
summarization:
  enabled: true
  trigger:
    - type: tokens
      value: 32000
  keep:
    type: messages
    value: 10
  preserve_recent_skill_count: 5

loop_detection:
  enabled: true
  warn_threshold: 3
  hard_limit: 5

tool_search:
  enabled: true

# ------ Phase 3 ------
memory:
  enabled: true
  storage_path: data/deerflow_memory.json
  max_facts: 100
  max_injection_tokens: 1500

subagents:
  timeout_seconds: 900

circuit_breaker:
  failure_threshold: 5
  recovery_timeout_sec: 60

guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: [place_real_order, upsert_holding, confirm_rebalance_draft]
```

## 收益预估

| 指标 | 当前 | Phase 1 后 | Phase 2 后 | Phase 3 后 |
|------|------|-----------|-----------|-----------|
| 多轮对话轮数 | 1（无状态） | 20+ | 50+ | 50+ |
| 上下文 token 上限 | 无保护 | 无保护 | 32K 自动压缩 | 32K 自动压缩 |
| 标题质量 | "AAPL 会话" | AI 语义标题 | AI 语义标题 | AI 语义标题 |
| 记忆跨会话 | ❌ | ❌ | ❌ | ✅ 偏好/关注持久化 |
| 复杂分析并行化 | ❌ | ❌ | ❌ | ✅ 子智能体并行 |
| API 故障恢复 | 无保护 | 无保护 | 无保护 | ✅ 熔断器 |
| 工具滥用防护 | 纯 LLM 自觉 | 纯 LLM 自觉 | 循环检测 | ✅ Guardrails |

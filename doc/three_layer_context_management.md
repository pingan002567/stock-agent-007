# 三层上下文管理设计

参考 OpenCode 的 compaction / handoff / session state 模式，为 AI Stock Workbench 的 Copilot 对话系统设计跨轮上下文管理方案。

## 1. 问题

### 1.1 症状

同一 session 内，用户说 "确认草案"（触发 rebalance workflow）后，再说 "你好"，AI 模型会级联调用 10 个工具（个股分析、历史行情、草案列表、生成拟单、交易审查、confirm 等），并报错 `draft is already confirmed_no_execution`。

### 1.2 根因

两层上下文同时泄漏到模型：

| 层次 | 机制 | 内容 | 问题 |
|---|---|---|---|
| DeerFlow Checkpointer | `thread_id=session_id` → `SqliteSaver` 自动恢复 `ThreadState.messages` | 前两轮的完整 HumanMessage + AIMessage + ToolMessage（含 raw error 原文），累计 90+ checkpoint / 4.7MB | 模型看到 `"error: draft must be confirmed_no_execution"` 以为用户想"继续修复" |
| Prompt Envelope | `context["previous_turn"]` 包含 `_build_previous_turn_summary()` 产的 raw error conclusion | `"AI流处理异常中断: draft must be confirmed_no_execution before review..."` | 同样被模型理解为"需要继续操作" |

这两条管线互相独立、并行注入，但都携带了执行痕迹而非结构化结果。

### 1.3 临时方案（greeting hack）的问题

用 `intent_router` 硬编码问候语列表 + thread_id 切换来 bypass checkpointer，但：

- 硬编码列表不完整（"嗨"、"喂" 不匹配）
- 只覆盖 greeting 场景，不处理其他"不相关消息"
- 依赖对消息内容的分类，而非对上下文相关性的判断

## 2. DeerFlow 上下文机制回顾

### 2.1 Checkpointer

DeerFlow 使用 LangGraph `SqliteSaver`，保存在 `data/deerflow_checkpoints.sqlite3`：

```sql
CREATE TABLE checkpoints (
    thread_id     TEXT,    -- 会话标识，当前 = session_id
    checkpoint_id TEXT,    -- 每个 graph node 一个 UUID
    checkpoint    BLOB,    -- ThreadState 序列化，~50-90KB/个
    metadata      BLOB     -- {"source": "loop", "step": 91}
);
PRIMARY KEY (thread_id, checkpoint_id)
```

**关键行为**：`DeerFlowClient.stream()` 每次创建新 state `{"messages": [HumanMessage(content=message)]}`，但 `agent.stream(state, config={thread_id: ...})` 时，LangGraph 从 checkpointer 加载该 thread_id 的全量 ThreadState.messages 并合并新消息 → 模型看到所有历史。

**量级**：一个活跃 session 积累 90-242 个 checkpoint，总大小 4.7-33MB。

### 2.2 Prompt Envelope

`render_prompt_envelope()` 生成 JSON，作为 `HumanMessage.content` 传入 DeerFlow：

```json
{
    "user_message": "你好",
    "current_page": "holdings",
    "skill_trace": [...],
    "condensed_stock_context": {...},
    "condensed_page_context": {...},
    "safety_constraints": [...],
    "previous_turn": {
        "previous_question": "确认草案",
        "previous_conclusion": "AI流处理异常中断: draft must be confirmed_no_execution...",
        "previous_draft_id": "d1"
    }
}
```

`previous_turn` 和 checkpointer 的 ThreadState.messages **并行** 注入模型上下文。

## 3. OpenCode 参考模式

OpenCode 不是开源项目，但其系统提示和工具暴露出了上下文管理的三层架构：

```
第1层: Live Context
  当前对话的完整 messages 列表 → orchestrator 直接看到
  上限: context window - system prompt

第2层: Compaction（自动触发）
  上下文逼近 window 上限 → 调用 compaction agent →
  生成结构化摘要 → 摘要替代历史 → 为新消息腾空间

第3层: Handoff + Session State（显式触发）
  用户换 session → /handoff 命令 →
  生成 {current_state, completed_todos, pending_work, key_files} →
  新 session 注入这个摘要，不再携带执行痕迹
```

**核心模式**：原始执行痕迹不跨轮传递，只传递结构化摘要。

| 模式 | OpenCode | 当前本项目 |
|---|---|---|
| 跨轮上下文 | orchestrator 过滤 → 结构化摘要注入 subagent prompt | 无过滤 → raw error + 全量 ThreadState dump |
| Agent 状态持久化 | subagent 内部 checkpointer（session_id 续接用） | DeerFlow checkpointer（跨轮复用） |
| 上下文体积 | 摘要 < 500 bytes | previous_turn + ThreadState = KB ~ MB 级 |

## 4. 三层上下文管理设计

### 4.1 架构总览

```
Session（一个 Chat）
 │
 ├─ Run 1: "确认草案"
 │   thread_id = run_1（全新, checkpointer 仅做 run 内恢复）
 │   context = { turn_summary: null, session_state: null, domain_ctx }
 │   output → tool_sequence → final_answer / error
 │   after:  generate turn_summary_1 → update session_state
 │
 ├─ Run 2: "做审查"
 │   thread_id = run_2（全新）
 │   context = { turn_summary: turn_summary_1, session_state, domain_ctx }
 │   模型看到: "上轮确认草案成功, 当前 state: d1=confirmed"
 │   output → 调 create_pre_trade_review(d1) ✅
 │
 ├─ Run 3: "你好"
 │   thread_id = run_3（全新）
 │   context = { turn_summary: turn_summary_2, session_state, domain_ctx }
 │   模型看到: "上轮做完审查, 当前无待处理"
 │   output → 正常回复问候 ✅（不级联工具）
 │
 └─ Run 4: "分析 AAPL"
     thread_id = run_4（全新）
     context = { turn_summary: turn_summary_3, session_state, domain_ctx }
     模型看到: "上轮是闲聊, 当前无待处理"
     output → 正常调用 stock-researcher 工具 ✅（不级联 rebalance 工具）
```

### 4.2 第 1 层：Run Context（单次执行的上下文，不跨轮继承）

**职责**：为每一次 `DeerFlowClient.stream()` 提供执行上下文。每次 run 全新构建，不含历史执行痕迹。

```python
# copilot_service.py stream_run()
thread_id = run_id                      # 每次新, 不继承 checkpointer
context["turn_summary"]   = turn_summary   # 第2层
context["session_state"]   = session_state  # 第3层
context["previous_turn"]   = None           # 删除
previous_turns             = []             # 删除
session_id_for_deerflow    = None           # → DeerFlow 用 run_id
```

**DeerFlow 侧**：`thread_id = run_id` 意味着每次 run 是全新的 checkpointer key，不存在跨轮恢复。

**Prompt Envelope 变化**：

```json
{
    "user_message": "做审查",
    "skill_trace": [...],
    "condensed_stock_context": {...},
    "turn_summary": {                          // 替代 previous_turn
        "outcome": "success",
        "summary": "草案 d1 已确认。可创建交易前审查。",
        "last_draft_id": "d1",
        "last_draft_status": "confirmed_no_execution"
    },
    "session_state": {                         // 替代 conversation_history
        "active_draft": {"id":"d1", "symbol":"AAPL", "status":"confirmed"},
        "pending_actions": ["草案 d1 可创建交易前审查"]
    }
}
```

### 4.3 第 2 层：Turn Summary（每轮结束自动生成）

**职责**：把一轮 run 的 tool 调用序列 + 结果 压缩为结构化摘要。

**生成时机**：`stream_run` 中收到 `final` 或 `error` 事件后。

**输入来源**：本轮 SSE 事件中的 `tool_result` 和 `final`/`error` 事件 payload（运行时数据，不查 DB）。

```python
@dataclass
class TurnSummary:
    question: str             # 用户消息原文（截断 100 字）
    intent: str               # 路由意图
    outcome: str              # "success" | "error" | "timeout"
    summary: str              # 人类可读的一句话摘要
    state_changes: dict       # 本轮产生的状态变更
    error_hint: str | None    # 错误分类标签（非 raw error）

def _classify_outcome(final_payload, error_payload) -> str:
    if not error_payload:
        return "success"
    error_msg = error_payload.get("error", "").lower()
    if "timeout" in error_msg or "timed out" in error_msg:
        return "timeout"
    return "error"

def _error_hint(error_payload) -> str | None:
    if not error_payload:
        return None
    error_msg = str(error_payload.get("error", ""))
    if "draft must be confirmed" in error_msg:
        return "DRAFT_NOT_CONFIRMED"
    if "requires an explicit confirmed draft_id" in error_msg:
        return "MISSING_DRAFT_ID"
    if "draft is already" in error_msg and "confirmed" in error_msg:
        return "DRAFT_ALREADY_CONFIRMED"
    if "expired" in error_msg:
        return "DRAFT_EXPIRED"
    if "permission" in error_msg.lower() or "denied" in error_msg.lower():
        return "PERMISSION_DENIED"
    return "UNKNOWN"

def _build_summary_text(outcome, tool_events, error_hint) -> str:
    parts = []
    for t in tool_events:
        if t["tool"] == "generate_draft_order":
            parts.append(f"生成了 {t['symbol']} 草案")
        elif t["tool"] == "confirm_rebalance_draft":
            parts.append(f"确认了草案")
        elif t["tool"] == "create_pre_trade_review":
            parts.append(f"创建了交易前审查")
    
    if outcome == "error":
        hints = {
            "DRAFT_NOT_CONFIRMED": "草案需先在持仓页确认后才能审查",
            "MISSING_DRAFT_ID": "请先生成草案再操作",
            "DRAFT_ALREADY_CONFIRMED": "草案已是已确认状态，无需重复操作",
            "DRAFT_EXPIRED": "草案已过期，需要重新生成",
            "PERMISSION_DENIED": "权限不足，该操作仅限页面显式触发",
        }
        parts.append(hints.get(error_hint, "操作未完成"))
    
    return "。".join(parts) if parts else "无具体操作。"

def _extract_state_changes(tool_events) -> dict:
    return {
        "generated_drafts": [
            {"id": t["result"]["draft_id"], "symbol": t["args"]["symbol"]}
            for t in tool_events
            if t["tool"] == "generate_draft_order" and t["status"] == "done"
        ],
        "confirmed_drafts": [
            {"id": t["result"]["draft_id"]}
            for t in tool_events
            if t["tool"] == "confirm_rebalance_draft" and t["status"] == "done"
        ],
        "created_reviews": [
            {"id": t["result"]["review_id"]}
            for t in tool_events
            if t["tool"] == "create_pre_trade_review" and t["status"] == "done"
        ],
    }
```

**存储**：内存中（`self._turn_summaries: dict[str, list[TurnSummary]]`），key 为 session_id。不持久化到 DB——CopilotMessage 表已有完整原始数据。

### 4.4 第 3 层：Session State（跨轮累积的状态快照）

**职责**：跨多轮 run 跟踪关键对象的生命周期状态，给模型提供 "现在是什么状态" 的简洁视图。

```python
@dataclass
class SessionState:
    active_drafts: dict[str, dict]   # draft_id → {symbol, status, created_at}
    active_reviews: dict[str, dict]  # review_id → {draft_id, status, created_at}
    summary_text: str               # 会话级一句话总结
    total_runs: int
    
    def apply_turn(self, turn: TurnSummary):
        """用新轮次摘要更新累积状态"""
        for d in turn.state_changes.get("generated_drafts", []):
            self.active_drafts[d["id"]] = {
                "symbol": d["symbol"],
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }
        for d in turn.state_changes.get("confirmed_drafts", []):
            if d["id"] in self.active_drafts:
                self.active_drafts[d["id"]]["status"] = "confirmed"
        for r in turn.state_changes.get("created_reviews", []):
            self.active_reviews[r["id"]] = {
                "draft_id": r.get("draft_id"),
                "status": "created",
                "created_at": datetime.now().isoformat()
            }
        self.total_runs += 1
        self.summary_text = turn.summary
    
    def to_context(self) -> dict:
        """输出给 prompt envelope 的 session_state 字段"""
        pending_drafts = {k: v for k, v in self.active_drafts.items() if v["status"] == "pending"}
        confirmed_drafts = {k: v for k, v in self.active_drafts.items() if v["status"] == "confirmed"}
        
        actions = []
        for d_id, d in pending_drafts.items():
            actions.append(f"草案 {d_id}({d['symbol']}) 待确认")
        for d_id, d in confirmed_drafts.items():
            actions.append(f"草案 {d_id} 可创建交易前审查")
        
        return {
            "pending_drafts": [{"id": k, "symbol": v["symbol"]} for k, v in pending_drafts.items()],
            "confirmed_drafts": [{"id": k, "symbol": v["symbol"]} for k, v in confirmed_drafts.items()],
            "active_reviews": [{"id": k, **v} for k, v in self.active_reviews.items()],
            "pending_actions": actions,
            "summary": self.summary_text,
            "total_runs": self.total_runs,
        }
```

**存储**：`self._session_states: dict[str, SessionState]`（内存）。轻量持久化到 `app_config` 可选——服务重启后丢失不影响功能，只是首轮缺少上下文。

### 4.5 数据流全链路对比

```
当前（有问题）:
  DeerFlow Checkpointer: ThreadState.messages(全部历史, ~4MB) → 模型
  Prompt Envelope:       previous_turn(raw error 原文, ~500B)  → 模型
  → 双重注入 → 模型看到 "确认草案 error" → 级联 10 工具

优化后:
  DeerFlow Checkpointer: thread_id=run_id → 每次新, 无历史       → 模型
  Prompt Envelope:       turn_summary(structured, ~200B)         → 模型
                       + session_state(draft/review 状态, ~300B) → 模型
  → 整洁上下文 → 模型看到 "草案已确认" → 正确行为
```

### 4.6 与 greeting hack 的对比

| 场景 | greeting hack | 三层上下文 |
|---|---|---|
| "确认草案" → "你好" | 命中硬编码列表 → 不调工具 ✅ | 摘要"草案已确认" → 不调工具 ✅ |
| "确认草案" → "嗨" | 不在列表 → 级联 ❌ | 摘要"草案已确认" → 不调工具 ✅ |
| "确认草案" → "做审查" | 正常 ✅ | 摘要体"草案已确认" + state → 正确调工具 ✅ |
| "确认草案" → "分析 AAPL" | 正常 ✅ | 摘要体 + stock context → 分析 AAPL ✅ |
| "确认草案" → "今天天气" | 不在列表 → 可能级联 ❌ | 摘要"草案已确认" → 不调工具 ✅ |
| 首轮消息 | 无影响 ✅ | 无 turn_summary → 正常 ✅ |

## 5. 实施计划

### 5.1 改动文件

| 文件 | 删除 | 新增 |
|---|---|---|
| `copilot_service.py` | `_build_previous_turn_summary()` | `TurnSummary` + `SessionState` 类型定义 |
| | `_build_conversation_history()` | `_build_turn_summary()` + 辅助函数 |
| | `is_greeting` 分支 + `session_id=state.session_id` | `thread_id=run_id`（session_id=None 路径） |
| | `context["previous_turn"]` | `context["turn_summary"]` + `context["session_state"]` |
| `prompt_envelope.py` | `if context.get("greeting")` 分支 | `if turn := context.get("turn_summary")` → 注入 `turn_summary` |
| `intent_router.py` | greeting 硬编码列表（greeting intent + plans["greeting"]） | — |
| `deerflow_client.py` | —（不碰，thread_id=run_id 路径已有） | — |

**net 变更**：删除 ~35 行 hack，新增 ~90 行结构化摘要逻辑。

### 5.2 TurnSummary 构建的输入数据来源

```
stream_run() 中遍历 SSE 事件时收集:
  ├─ tool_call_events:    [{"tool":"confirm_rebalance_draft", "args":{"draft_id":"d1"}}]
  ├─ tool_result_events:  [{"tool":"confirm_rebalance_draft", "status":"done", "result":{"draft_id":"d1"}}]
  ├─ final_payload:       {"conclusion":"草案已确认","draft_id":"d1","draft_status":"confirmed"}
  ├─ error_payload:       {"error":"draft is already confirmed_no_execution"} 或 None
  └─ intent:              "rebalance_plan"

→ _build_turn_summary(intent, user_message, tool_events, final_payload, error_payload)
→ TurnSummary → self._turn_summaries[session_id].append()
             → self._session_states[session_id].apply_turn()
```

### 5.3 注入时机

```python
# copilot_service.py stream_run()
context = self.copilot_context_builder.build(...)

# 获取上一轮摘要和当前 session 状态
last_turn = self._get_last_turn_summary(state.session_id)
session_state = self._get_session_state(state.session_id)

if last_turn:
    context["turn_summary"] = last_turn.to_context()
if session_state:
    context["session_state"] = session_state.to_context()

runtime_context = {**context, "_authority_level": ...}

# 传给 DeerFlow — 关键：session_id=None
async for event in self.deerflow.stream(
    ...
    session_id=None,  # → deerflow 内部用 run_id 做 thread_id
):
```

### 5.4 生命周期

```
Session 创建 → SessionState 初始化
  ↓
Run 1 → stream → collect tool_events → final → build TurnSummary_1
  ↓                    → SessionState.apply_turn(TurnSummary_1)
Run 2 → stream → context = { turn_summary: TurnSummary_1, session_state }
  ↓                    → collect tool_events → final → build TurnSummary_2
  ↓                    → SessionState.apply_turn(TurnSummary_2)
Run N → ...
  ↓
Session 删除 → TurnSummary[] + SessionState 随内存释放
```

## 6. 风险与退化

### 6.1 服务重启后状态丢失

`TurnSummary` 和 `SessionState` 全在内存中。重启后首轮消息没有历史上下文，但不影响功能——模型仅基于当前消息 + domain context 推理。

**后续可选优化**：轻量持久化到 `app_config` 表。

### 6.2 摘要信息不足

如果 `_build_summary_text` 漏掉了关键信息（如某个 tool 的结果没有被摘要化），模型可能缺少决策依据。但相比当前 raw error 注入的问题，信息不足远好于信息错误。

**缓解**：`_extract_state_changes` 白名单方式提取 state，宁可漏不可错。

### 6.3 长时间对话的状态膨胀

如果 session 内创建了大量 drafts / reviews，`SessionState.active_drafts` 可能累积到很多条目。注入给模型的 `session_state` 会因此增长。

**缓解**：`to_context()` 只输出 pending + confirmed 状态，已 resolved 的（如已创建 review 后）从 active 移除。每轮 `apply_turn` 时清理已处理的条目。

### 6.4 Error 分类不完整

`_error_hint` 依赖关键词匹配，新增 error 类型可能需要更新匹配规则。

**缓解**：default 分支 `"UNKNOWN"` → 摘要为 `"操作未完成"`，不展示 raw error。

### 6.5 与现有 greeting 方案的兼容

实施时按以下顺序：
1. 先实现第 1、2、3 层
2. 验证通过后删除 greeting hack（实现三层方案已覆盖其所有场景）

## A. 附录：设计原则对照

| 原则 # | 描述 | 三层上下文的体现 |
|---|---|---|
| 4 | DeerFlow 只承担 agent runtime 边界 | checkpointer 限为 run 内恢复，不做跨轮上下文 |
| 9 | Embedded prompt 只接收精简 envelope | turn_summary 替代 raw error，session_state 替代 conversation_history |
| 13 | 确认只能由 HTTP/UI 显式触发 | confirm_rebalance_draft 不做为跨轮"自动重试"的依据 |
| 16 | AI Chat 是统一指挥入口 | 上下文管理在 copilot_service 层统一控制 |

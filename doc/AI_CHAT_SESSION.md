# AI Chat 会话与消息架构

本文档记录 Stock Workbench AI Chat（右侧 Copilot 面板）的会话管理、消息流和前端状态机设计。涉及的数据流跨越 `frontend` → `backend/api` → `copilot_service` → `persistence`。

---

## 1. 产品概念

### 1.1 Session（会话）

Session 是用户与 AI 的一次"对话上下文"。一个 session 包含多条消息（message），每条消息归属于一个 `run_id`。

用户可以在左侧会话列表切换、重命名、删除 session。新消息默认落在当前 session 内。

**Session 不隔离数据**（可见性不写入后端权限模型），仅用于前端组织和上下文递送。

### 1.2 Run（执行回合）

Run 是用户一次发送→AI 一次回复的完整回合。每次 `handleSend` 产生一个唯一的 `run_id`。

```
run_id = "run_" + uuid4().hex[:10]
```

一个 run 产生的消息序列（按时间排序）：

```
user_message → (tool_call → tool_result)* → final_answer | error
```

**关键约束：** 每个 run 有且仅有一个 `user_message`，有且至少一个 `final_answer`（正常结束）或 `error`（异常结束）。

### 1.3 Message（消息）

消息是持久化的最小单元。后端 `stream_run()` 中每个 SSE 事件都通过 `_persist_stream_event()` 写入 `copilot_message` 表。

消息类型：

| kind | role | 说明 | 前端渲染 |
|---|---|---|---|
| `user_message` | user | 用户输入 | 气泡，蓝色 |
| `tool_call` | assistant | AI 决定调用工具 | ToolCard |
| `tool_result` | tool | 工具执行结果 | 与 tool_call 合并为 ToolCard 详情 |
| `partial_answer` | assistant | AI 流式输出片段 | 不独立渲染，合并成最终气泡 |
| `final_answer` | assistant | AI 最终结论 | 气泡，灰色 |
| `error` | system | 运行时异常 | 气泡，红色 |
| `skill_trace` | system | 声明式 skill 链 | 不渲染 |
| `reasoning` | system | AI 推理过程 | 不直接渲染，驱动打字机效果 |

---

## 2. 数据模型

### 2.1 存储

```sql
-- copilot_session
session_id    TEXT PRIMARY KEY         -- "session_" + uuid
title         TEXT                     -- 用户可见标题
status        TEXT DEFAULT 'active'
current_page  TEXT                     -- 最后停留页面
anchor_symbol TEXT                     -- 关联股票代码
authority_level TEXT                   -- A2/A3/A4
created_at    TEXT
updated_at    TEXT
last_message_at TEXT                   -- 最后消息时间，用于排序

-- copilot_message
message_id    TEXT PRIMARY KEY         -- "message_" + uuid
session_id    TEXT → copilot_session
role          TEXT                     -- user / assistant / tool / system
kind          TEXT                     -- user_message / tool_call / tool_result / ...
text          TEXT
page          TEXT
symbol        TEXT
run_id        TEXT                     -- "run_" + uuid
task_id       TEXT
client_message_id TEXT
created_at    TEXT
payload       TEXT(JSON)
```

### 2.2 查询约定

所有消息查询统一按 `created_at ASC, message_id ASC` 排序，确保顺序确定性。

```sql
-- 获取 session 所有消息
SELECT * FROM copilot_message
WHERE session_id = ?
ORDER BY created_at ASC, message_id ASC;

-- 获取 session 特定 run 的消息
SELECT * FROM copilot_message
WHERE session_id = ? AND run_id = ?
ORDER BY created_at ASC, message_id ASC;
```

### 2.3 级联删除

`DELETE FROM copilot_session` 时同步删除该 session 下所有 `copilot_message`。

---

## 3. 前端状态机

### 3.1 核心状态

```
copilotStreaming: boolean      ← 是否有活跃的 SSE stream
currentSessionId: string|null  ← 当前选中的 session
messages: CopilotMessage[]     ← 当前 session 的全部消息
input: string                  ← 输入框文本
sending: boolean               ← 发送请求中（POST 到 SSE 建立之间）
```

### 3.2 全局流程

```
Page Load ──→ loadSessions()
                  │
                  ├─→ fetchSessions() → setSessions()
                  └─→ loadMessages(first_session_id) → setMessages()

Send ──→ handleSend()
            │
            ├─1. sendMessage() → POST → 创建 run_id, 保存 user_message
            ├─2. loadMessages(sid) → 加载 user_message（立即展示）
            ├─3. new EventSource(stream_url) → SSE 连接
            │      ├─ "reasoning" → streamingReasoningText += text
            │      ├─ "final"     → done()
            │      └─ "error"     → done()
            │
            ├─4. [done] → loadMessages(sid), loadSessions()
            │              └─ messages 刷新，含 tool_call/tool_result/final_answer
            │
            └─5. [stop] → es.close(), setCopilotStreaming(false)

SwitchSession ──→ switchSession(id)
                  ├─ es.close() + 重置 streaming
                  ├─ setCurrentSessionId(id)
                  ├─ setMessages([])
                  └─ loadMessages(id)

NewSession ──→ handleNewSession()
              ├─ es.close() + 重置 streaming
              ├─ createSession()
              ├─ setCurrentSessionId(new_id)
              └─ setMessages([])

DeleteSession ──→ handleDeleteSession(sid)
                 ├─ deleteSession(sid) → 后端级联删除消息
                 ├─ 从 sessions[] 移除
                 ├─ 若删除的是当前 session → 切换到下一个
                 └─ loadMessages(next_session_id)
```

### 3.3 `pairMessages` 消息配对

`pairMessages(msgs)` 将扁平消息列表转为有序渲染列表：

```
输入: CopilotMessage[]（DB 顺序持久化消息）
输出: MsgOrTool[]（渲染队列）

规则:
1. tool_call + 后一条是 tool_result → 配对为 ToolCard(done=true)
2. tool_call + 后一条不是 tool_result → 检查 run 是否已完成
   - run 有 final_answer/error → ToolCard(done=true, failed=true)
   - run 没有 final_answer/error → ToolCard(done=false)
3. 连续 partial_answer → 合并为一条消息
4. user_message / final_answer / error → 渲染为消息气泡
5. tool_result / skill_trace / reasoning → 不独立渲染
```

**已完成 run 的判定：** 消息列表中包含 `final_answer` 或 `error` 类型的消息且 `run_id` 匹配。

> 设计决策：不按 `run_id` 过滤消息。同一 session 内所有历史消息全部可见。工具配对仅依赖位置相邻 + run 完成状态。无需额外标记或 filter。

---

## 4. 关键设计决策

### 4.1 Session 隔离不依赖前端

Session 隔离完全由后端 SQL 的 `WHERE session_id = ?` 保证。前端不维护任何跨 session 的 LRU cache 或过滤逻辑。

结论：前端 `pairMessages` 不接收 `currentRunId` 参数，也不过滤任何消息。

### 4.2 Stale 工具不阻塞 UI

Stream 中断时（网络断开、后端崩溃、用户刷新），部分 `tool_call` 可能没有对应的 `tool_result`。前端通过 run 完成状态判断：

- 如果该 run 已有 `final_answer`（正常结束）或 `error`（异常结束），但 `tool_call` 无 `tool_result` → 标记为"失败"（红点）
- 如果该 run 尚未结束（仍在 streaming 中）→ 标记为"调用中…"（黄点）

这样即使用户刷新页面后重新进入 session，所有工具状态都是确定的，不会出现永远"调用中"的幽灵工具。

### 4.3 `done()` 回调必须有 session 守卫

`done()` 是 EventSource 的回调，通过闭包捕获 `sid`（发送时的 session_id）。如果用户在 streaming 过程中切换了 session，`done()` 触发的 `loadMessages(sid)` 会覆盖当前 session 的消息列表。

守卫逻辑：

```typescript
const done = () => {
  if (sid !== currentSessionId) return;  // 丢弃旧 session 的回调
  // ...正常收尾
};
```

### 4.4 Session 切换必须关闭旧 EventSource

任何 session 切换、新建、删除操作都应先关闭当前 EventSource，避免：
- 旧 stream 继续浪费后端资源
- 旧 stream 的 `done()` 回调被 native `error` 事件触发，污染当前 session 数据

### 4.5 自动标题

Session 的标题来自 `_derive_title()`：

```
if anchor_symbol → "{SYMBOL.upper()} 会话"
elif message      → message 前 24 字符
else              → "新会话"
```

初始 `createSession("新会话")` 的标题是"新会话"，后端 `_refresh_session_title` 在第一条消息后更新。

---

## 5. 边界情况与防御

| 场景 | 现有防护 | 状态 |
|---|---|---|
| 刷新页面后恢复 | `loadSessions` 自动加载第一个 session | ✅ |
| 空 session（无消息） | 显示 empty state + 建议快捷入口 | ✅ |
| Streaming 中切 session | `switchSession` 关闭旧 EventSource + `done()` 守卫 | ⚠️ 需加守卫 |
| Streaming 中新建 session | `handleNewSession` 关闭旧 EventSource | ⚠️ 需加关闭 |
| 删除当前 session | 自动切换到下一个 session（或 null） | ✅ |
| 删除最后一个 session | `currentSessionId = null`，显示 empty state | ✅ |
| 删除 session 时级联消息 | 后端 DELETE 同步删除 `copilot_message` | ✅ |
| 后端 stream 崩溃 | 持久化 `error` + `final_answer`，前端显示"失败"工具 | ✅ |
| 同一 session 多轮对话 | 所有 run 的消息都可见，`_build_conversation_history` 排除当前 run | ✅ |
| 快速连续发送（防抖） | `sendingRef.current` 互斥锁 | ✅ |
| `done()` 被两个事件重复触发 | 二次执行是幂等的（es.close() 安全，loadMessages 幂等） | ✅ |

---

## 6. 待修复项

### 6.1 `done()` 缺 session 守卫

**位置：** `handleSend` 内部的 `done` 闭包，约第 335 行

**修复：**
```typescript
const done = () => {
  if (sid !== currentSessionId) return;  // ← 新增
  // ...rest
};
```

### 6.2 `switchSession` 缺 EventSource 关闭

**位置：** `switchSession` 函数

**修复：** 在 `setCurrentSessionId` 之前增加：
```typescript
eventSourceRef.current?.close();
eventSourceRef.current = null;
setCopilotStreaming(false);
sendingRef.current = false;
setSending(false);
```

### 6.3 `handleNewSession` 缺 EventSource 关闭

**位置：** `handleNewSession` 函数

**修复：** 在 `try` 之前增加：
```typescript
eventSourceRef.current?.close();
eventSourceRef.current = null;
setCopilotStreaming(false);
sendingRef.current = false;
setSending(false);
```

---

## 7. 消息生命周期示例

```
Session: "AAPL 会话"
  Run run_001:
    10:00:00  user_message  "分析 AAPL 仓位风险"
    10:00:01  tool_call     get_portfolio_snapshot
    10:00:02  tool_result   {holdings: [...]}                ← ToolCard(完成)
    10:00:03  tool_call     analyze_portfolio_risk
    10:00:04  tool_result   {risk: "concentrated"}            ← ToolCard(完成)
    10:00:05  final_answer  "AAPL 仓位集中度偏高…"          ← AI 气泡

  Run run_002:
    10:01:00  user_message  "生成调仓草案"
    10:01:01  tool_call     generate_draft_order
    10:01:02  [stream crash - no tool_result, no final_answer]
                                                            ← ToolCard(失败)

  Run run_003:
    10:02:00  user_message  "继续，帮我生成草案"
    10:02:01  tool_call     generate_draft_order
    10:02:02  tool_result   {draft_id: "draft_xxx"}          ← ToolCard(完成)
    10:02:03  final_answer  "草案已生成…"                    ← AI 气泡
```

渲染效果：三条消息（用户气泡 ×3 + AI 气泡 ×2）+ 三个 ToolCard（完成×2 + 失败×1）。

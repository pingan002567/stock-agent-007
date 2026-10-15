# AI Chat 气泡展示与对话流

本文档描述 Stock Workbench Copilot 面板的前端气泡渲染机制、对话流状态机，以及当前诊断出的待修复问题。与 `AI_CHAT_SESSION.md`（会话与消息架构）互补。

---

## 1. 渲染管线

### 1.1 数据流

```
Backend SSE stream                    Frontend
─────────────────                    ────────
persist → yield "reasoning"    ──→   streamingReasoningText += text
persist → yield "tool_call"    ──→   (未监听)
persist → yield "tool_result"  ──→   (未监听)
persist → yield "partial_answer" ──→  (未监听，但写入 DB)
persist → yield "final"        ──→   done() → loadMessages(sid)
                                      → setMessages(全部持久化消息)
                                      → pairMessages() → 渲染

Post-stream 渲染入口：
  pairMessages(messages) → MsgOrTool[]
    ├── user_message     → <MessageBlock className="msg user" />
    ├── final_answer     → <MessageBlock className="msg ai" />
    ├── partial_answer   → <MessageBlock className="msg ai" />  ← 问题
    ├── error            → <MessageBlock className="msg error" />
    ├── tool_call+result → <ToolCard done=true />   (绿点)
    ├── tool_call 无配对 → <ToolCard done=false />  (黄点，streaming 中)
    │                       <ToolCard failed=true /> (红点，run 已完结但无结果)
    └── skill_trace / reasoning → 不渲染

Streaming 期间独立渲染：
  copilotStreaming=true → <div className="msg ai streaming">
    显示 streamingReasoningText（从 reasoning SSE 累积）
```

### 1.2 MessageBlock 组件

```typescript
function MessageBlock({ msg }) {
  // 根据 role + kind 决定 CSS class 和 body
  user         → "msg user"     → Markdown(text)
  final_answer → "msg ai"       → Markdown(stripToolCallTags(conclusion))
  error        → "msg error"    → ⚠️ + error text
  partial_answer → "msg ai"     → Markdown(text)          ← 问题
  其他         → return null
}
```

### 1.3 ToolCard 组件

```typescript
function ToolCard({ name, done, failed }) // 三态：
  failed=true  → 红点 + "失败"            ← CSS: .tool-dot.fail
  done=true    → 绿点 + "完成"            ← CSS: .tool-dot.ok
  done=false   → 黄点 + "调用中…"         ← CSS: .tool-dot.busy

  点击展开 resultText（最多 300 字符预览）
```

---

## 2. 对话流状态机

### 2.1 状态定义

```
空闲（idle）:
  copilotStreaming=false, sending=false
  用户可输入，可发送

发送中（sending）:
  sending=true, copilotStreaming=false
  handleSend 执行中（POST 请求等待 run_id）

流式（streaming）:
  copilotStreaming=true, sending=false
  EventSource 连接中，SSE 事件持续到达

停止（stopped）:
  用户点击停止 → handleStop() → ES.close()
  → native error 事件触发 done() → 回到 idle

完成（done）:
  ES 的 final/error 事件 → done()
  → loadMessages + loadSessions → 回到 idle
```

### 2.2 状态迁移

```
         ┌─────────────────────────────────────┐
         │                                     │
         v                                     │
    ┌─────────┐   sendMessage    ┌──────────┐  │
    │  idle   │ ──────────────→  │ sending  │  │
    │         │                  │          │  │
    │ messages│                  │ POST     │  │
    │ loaded  │                  │ pending  │  │
    └────┬────┘                  └────┬─────┘  │
         │                            │        │
         │ ES final/error             │ POST   │
         │ done()                     │ done   │
         │                            │        │
         │    ┌──────────┐            │        │
         │    │streaming │ ←──────────┘        │
         │    │          │  new EventSource()   │
         │    │ SSE 到达 │                     │
         │    │ reason.. │                     │
         │    │ tool..   │                     │
         │    └────┬─────┘                     │
         │         │                           │
         │         │ ES final/error            │
         └─────────┘                           │
                                                │
         handleNewSession / switchSession ──────┘
         → 关 ES → idle
```

---

## 3. 诊断出的问题

### P0 — 数据完整性（会话隔离）

#### P0a: `done()` 无 session 守卫

**表现：** Session A 正在 streaming，用户切换到 Session B。A 的 stream 结束后 `done()` 触发，`loadMessages(sid)` 中的 `sid` 是 A（闭包捕获），此时 `messages` 属于 Session B → B 的消息被 A 的消息覆盖。

**根因：** `done` 是 EventSource 回调，`sid` 在 `handleSend` 执行时捕获。`currentSessionId` 是 React state，回调执行时可能已指向不同 session。

**代码位置：** `handleSend` 内部，约第 335 行

```typescript
const done = () => {
  // 缺少:
  // if (sid !== currentSessionId) return;
  setCopilotStreaming(false);
  // ...
  if (sid) { loadMessages(sid); loadSessions(); }
};
```

**修复：** 在 `done` 第一行加守卫 `if (sid !== currentSessionId) return;`

#### P0b: `switchSession` 不关 EventSource

**表现：** Session A streaming 中切到 Session B，A 的 ES 仍然存活。A 的 stream 结束后 native `error` 事件触发 `done()` → 同 P0a 的污染链。

**根因：** `switchSession` 未调用 `eventSourceRef.current?.close()`，也未重置 `copilotStreaming`。

**代码位置：** `switchSession` 函数，约第 253 行

**修复：** 在 `setCurrentSessionId` 之前关闭 ES + 重置 streaming 状态。

#### P0c: `handleNewSession` 不关 EventSource

**表现：** streaming 中点击"+ 新建会话"，旧 ES 继续运行，旧 `done` 回调可能污染新 session。

**根因：** 同 P0b，新建 session 时未清理旧 ES。

**代码位置：** `handleNewSession` 函数，约第 263 行

**修复：** 在 `createSession` 调用前关闭 ES + 重置 streaming 状态。

---

### P1 — 气泡渲染错误

#### P1a: `partial_answer` 在 stream 结束后渲染为独立气泡

**表现：** Stream 结束后 `loadMessages` 加载到 `partial_answer` 碎片。`pairMessages` 将它们合并为一条消息，与 `final_answer` 并列显示。

```
实际渲染：
  [用户] 分析 AAPL 风险
  [AI] AAPL 当前仓位集中度偏高，建议…   ← 合并的 partial_answer（重复！）
  [AI] AAPL 当前仓位集中度偏高，建议…   ← final_answer
```

**根因：** `pairMessages` 中的 `partial_answer` 分支只做了合并（merge consecutive），未检查该 run 是否已有 `final_answer`。`canRenderMessage` 放行了 `partial_answer`。

**代码位置：** `pairMessages` 函数，`partial_answer` 分支，约第 467 行

```typescript
} else if (ev.type === "partial_answer") {
  // 合并连续 partial_answer
  let merged = msg.text || "";
  let j = i + 1;
  while (j < msgs.length) {
    const nextEv = parseCopilotEvent(msgs[j]);
    if (nextEv.type !== "partial_answer") break;
    merged += msgs[j].text || "";
    j++;
  }
  out.push({ t: "msg", msg: { ...msg, text: merged } });  // ← 未检查 run 状态
  i = j;
}
```

**修复：** 进入 `partial_answer` 分支时，先检查 `completedRuns`——如果该 run 已有 `final_answer`，跳过碎片不渲染。

```typescript
if (msg.run_id && completedRuns.has(msg.run_id)) {
  i++;      // 跳过，因为最终内容在 final_answer 中
  continue;
}
```

#### P1b: `canRenderMessage` 误放 `partial_answer`

**根因：** `partial_answer` 在 `canRenderMessage` 中返回 `true`，导致 `pairMessages` 将其作为可渲染条目发出。即使不做合并（绕过 P1a 修复），单独一条 `partial_answer` 也会被渲染。

**修复：** 由 P1a 的跳过逻辑一并拦截，无需单独修改 `canRenderMessage`。

---

### P2 — 用户体验

#### P2a: Streaming 气泡显示的是 AI 推理文本

**表现：** Streaming 期间用户看到的是 AI 内部推理过程：

```
[AI] 我需要先获取持仓信息 <get_portfolio_snapshot>...</get_portfolio_snapshot>
     然后分析集中度风险...
```

而不是真正的回答。推理文本中还包含原始 XML 工具调用标签。

**根因：** 前端只监听了 `reasoning` SSE 事件：

```typescript
es.addEventListener("reasoning", handleStreamText);
```

未监听 `partial_answer` 事件（包含 AI 实际输出文本）。

**代码位置：** `handleSend` 中 ES 事件监听，约第 325-333 行

**修复：** 新增 `streamingAnswerText` 状态 + `partial_answer` 事件监听。

#### P2b: Stream 结束后推理文本残留

**表现：** `done()` 后，`streamingReasoningText` 状态保持旧值。在 `final_answer` 气泡出现的同时，屏幕上方可能残留旧的 streaming 推理文本（虽然 `copilotStreaming=false` 时 streaming 气泡不显示，但状态值不会立即清空，下次 streaming 时旧文本会闪一下）。

**根因：** `done()` 未清空 `streamingReasoningText`。

**修复：** 在 `done()` 中增加 `setStreamingReasoningText("")` 和 `setStreamingAnswerText("")`。

#### P2c: 工具调用全程不可见

**表现：** 用户发送消息后，看到用户气泡 + 推理文本 → 然后长时间"思考中…" → 突然所有工具卡片 + 最终回答一起出现。

**根因：** `tool_call`/`tool_result` SSE 事件未被前端监听，仅在 `done()` 的 `loadMessages` 中一次性加载。

**修复：** 在 `handleSend` 中增加 `tool_call`/`tool_result` 事件监听，到达时触发 `loadMessages(sid)` 刷新消息列表。

> 注意：`loadMessages(sid)` 在 streaming 期间调用是安全的 —— React 的 `setMessages` 会触发重渲染，新消息中的 `tool_call` 因无配对 `tool_result` 会显示为"调用中…"（黄点），直到 `tool_result` 到达后变为"完成"（绿点）。

---

## 4. 完整修复计划

### 4.1 改动清单

| # | 优先级 | 改动 | 位置 | 行数 |
|---|---|---|---|---|
| 1 | P0 | `done()` 加 session 守卫 | handleSend → done 闭包 | +1 |
| 2 | P0 | `switchSession` 关 ES + 重置 streaming | switchSession | +5 |
| 3 | P0 | `handleNewSession` 关 ES + 重置 streaming | handleNewSession | +5 |
| 4 | P1 | `pairMessages` partial_answer 跳过已完成 run | pairMessages 内部 | +4 |
| 5 | P2 | 新增 `streamingAnswerText` state + `partial_answer` 监听 + `tool_call`/`tool_result` 监听 | handleSend | +15 |
| 6 | P2 | `done()` 清空 streaming 文本 | done 闭包 | +2 |
| 7 | P2 | Streaming 气泡三态渲染 | JSX 条件渲染 | +2 |

**总行数：约 +34 / -0，仅修改一个文件（CopilotPanel.tsx）。**

### 4.2 代码修改详述

#### 4.2.1 新增状态（组件顶部，~line 155）

```typescript
const [streamingAnswerText, setStreamingAnswerText] = useState("");
```

#### 4.2.2 `switchSession`（~line 253）

```typescript
const switchSession = async (id: string) => {
  if (id === currentSessionId) return;
  eventSourceRef.current?.close();
  eventSourceRef.current = null;
  setCopilotStreaming(false);
  sendingRef.current = false;
  setSending(false);
  setCurrentSessionId(id);
  setMessages([]);
  setSessionOpen(false);
  setTypewriterDisplayed(0);
  prevTextLengthRef.current = 0;
  await loadMessages(id);
};
```

#### 4.2.3 `handleNewSession`（~line 263）

```typescript
const handleNewSession = async () => {
  eventSourceRef.current?.close();
  eventSourceRef.current = null;
  setCopilotStreaming(false);
  sendingRef.current = false;
  setSending(false);
  try {
    const session = await createSession("新会话");
    setSessions((prev) => [session, ...prev]);
    setCurrentSessionId(session.session_id);
    setMessages([]);
    setSessionOpen(false);
    setTypewriterDisplayed(0);
    prevTextLengthRef.current = 0;
  } catch { /* empty */ }
};
```

#### 4.2.4 `handleSend` 新增 SSE 监听（~line 333）

```typescript
// 监听 AI 实际输出文本
es.addEventListener("partial_answer", (streamEvent: Event) => {
  try {
    const data = JSON.parse((streamEvent as MessageEvent).data);
    const t = (data?.payload?.text as string) || "";
    if (t) setStreamingAnswerText((prev) => prev + t);
  } catch { /* empty */ }
});

// 监听工具调用 — 实时刷新消息列表
es.addEventListener("tool_call", () => { if (sid) loadMessages(sid); });
es.addEventListener("tool_result", () => { if (sid) loadMessages(sid); });
```

#### 4.2.5 `done` 闭包（~line 335）

```typescript
const done = () => {
  if (sid !== currentSessionId) return;
  setStreamingReasoningText("");       // ← 清空推理文本
  setStreamingAnswerText("");          // ← 清空回答文本
  setCopilotStreaming(false);
  sendingRef.current = false;
  es.close();
  eventSourceRef.current = null;
  setSending(false);
  if (sid) {
    loadMessages(sid);
    loadSessions();
  }
};
```

#### 4.2.6 `pairMessages` partial_answer 分支（~line 467）

```typescript
} else if (ev.type === "partial_answer") {
  // run 已完结 → 跳过 partial 碎片，避免与 final_answer 重复
  if (msg.run_id && completedRuns.has(msg.run_id)) {
    i++;
    continue;
  }
  let merged = msg.text || "";
  let j = i + 1;
  while (j < msgs.length) {
    const nextEv = parseCopilotEvent(msgs[j]);
    if (nextEv.type !== "partial_answer") break;
    merged += msgs[j].text || "";
    j++;
  }
  out.push({ t: "msg", msg: { ...msg, text: merged } });
  i = j;
}
```

#### 4.2.7 Streaming 气泡条件渲染（~line 649）

```tsx
{copilotStreaming && (
  <div className="msg ai streaming">
    <div className="msg-label">AI</div>
    <div className={streamingAnswerText || streamingReasoningText.length > typewriterDisplayed ? "" : "cursor-blink"}>
      {streamingAnswerText
        ? streamingAnswerText.trim().slice(-500)
        : typewriterText.trim()
          ? typewriterText.trim().slice(-500)
          : "思考中…"}
    </div>
    <div className="msg-time">now</div>
  </div>
)}
```

### 4.3 三态 streaming 气泡规则

| 条件 | 显示内容 | 光标 |
|---|---|---|
| `streamingAnswerText` 非空 | 回答文本 (slice -500) | 无光标闪烁 |
| 仅 `reasoning` 有内容 | 推理文本 (打字机效果) | 根据打字机进度 |
| 两者都空 | "思考中…" | 光标闪烁 |

---

## 5. 验证场景

| 场景 | 步骤 | 预期 |
|---|---|---|
| **正常对话** | 发消息 → 等待 stream 完成 | 推理文本 → 回答文本逐步出现 → 完成时所有工具可见，无重复气泡 |
| **工具实时可见** | 发涉及工具调用的消息 | 工具卡片按调用顺序逐一出现：黄点→绿点 |
| **切 session 安全** | Session A streaming → 切到 B | B 的 ES 关闭，B 正常加载 |
| **新建 session 安全** | Streaming 中点"+ 新建会话" | 旧 ES 关闭，空白 session |
| **删除当前 session** | 删除正在对话的 session | 自动切到下一个 session 或 null |
| **Stream 崩溃** | 后端异常中断 stream | 工具红点"失败" + 错误气泡 |
| **刷新页面** | F5 后恢复 | 首个 session 加载，所有工具状态正确 |
| **快速连续发送** | 快速按两次发送 | 第二次被 `sendingRef` 阻止 |
| **停止按钮** | 点"停止" | ES 关闭，已完成的工具和部分回答出现 |
| **同 session 多轮** | 连发 3 条消息 | 所有 run 的工具和气泡全部可见 |

---

## 6. 与其他文档的关系

| 文档 | 关系 |
|---|---|
| `AI_CHAT_SESSION.md` | 会话与消息的底层数据模型、后端 CRUD、SQL 隔离 |
| `AI_CHAT_BUBBLE.md`（本文） | 前端气泡渲染、对话流状态机、展示层问题诊断 |
| 后端 `copilot_service.py` | SSE 事件格式、`_persist_stream_event`、`_build_conversation_history` |
| 后端 `routes_copilot.py` | API 路由定义、StreamingResponse |

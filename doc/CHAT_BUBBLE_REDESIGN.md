# AI Chat Bubble & Dialogue Logic — 闭环改造方案

> 状态: 已定稿 · 待实施
> 关联: `frontend/src/components/features/CopilotPanel.tsx`
> 协同文件: `.sisyphus/plans/bubble-dialogue-closed-loop.md`（执行追踪）

---

## 1. 现状分析

### 1.1 前端渲染管线

当前 Copilot 面板的渲染流程如下：

```
CopilotPanel (686 行单体组件)
  ├── ContextCard                    ← 当前页面/持仓/盯盘摘要
  ├── pairMessages(messages) → MsgOrTool[]
  │     ├── user              → MessageBlock (琥珀色气泡)
  │     ├── final_answer      → MessageBlock (蓝色气泡, stripToolCallTags)
  │     ├── partial_answer    → MessageBlock (蓝色气泡, 合并连续分片)
  │     ├── tool_call+result  → ToolCard (可折叠)
  │     ├── error             → MessageBlock (红色错误)
  │     └── 其他              → null (隐藏 skill_trace/reasoning/孤立 tool_call)
  ├── [streaming] 底部打字机    ← streamingReasoningText 状态
  └── Input/发送区
```

### 1.2 流式传输流程

1. 用户发送 → `handleSend()` 调用后端创建 run → 打开 `EventSource`
2. SSE `reasoning` 事件 → 累积到 `streamingReasoningText`（独立状态）
3. 打字机效果在消息列表**底部**渲染 `streamingReasoningText`，但不在消息线程内
4. SSE `final` 事件 → 关闭 EventSource → **全量 reload 消息** → 重新渲染
5. reload 后，`pairMessages()` 将消息处理为用户气泡、AI 气泡、ToolCard

### 1.3 后端 SSE 事件类型

| 事件类型 | 内容 | 持久化 |
|---|---|---|
| `skill_trace` | 声明式技能链 | ✅ |
| `reasoning` | AI 内部推理文本 | ❌（仅流式） |
| `partial_answer` | 进行中的回答 token | ✅ |
| `tool_call` | 工具调用详情 | ✅ |
| `tool_result` | 工具执行结果 | ✅ |
| `error` | 错误详情 | ✅ |
| `final` | 最终回答 + 丰富元数据 | ✅ |

关键观察：`reasoning` 事件**不持久化**，`partial_answer` **持久化**。两者 payload 都含 `text`。

### 1.4 CopilotMessage 类型现状

```typescript
// frontend/src/api/client.ts
interface CopilotMessage {
  message_id: string;
  session_id: string;
  role: string;       // "user" | "assistant" | "tool" | "system"
  kind: string;       // "user_message" | "final_answer" | "partial_answer" | "tool_call" | "tool_result" | "error" | "skill_trace"
  text: string;
  payload: Record<string, unknown>;
  created_at: string;
  // ❌ run_id 缺失 — 后端实际返回，但类型未声明
}
```

---

## 2. 问题清单

| 编号 | 问题 | 影响 |
|---|---|---|
| **P1** | 推理文本与 AI 气泡分离 — 显示在面板底部，非消息线程内 | 用户看到悬空文字，流结束后消失，体验割裂 |
| **P2** | `partial_answer` 直到 stream 结束后才渲染 — SSE 事件到达时不渲染，等 "final" 全量 reload 后才出现 | 用户看不到 AI 实时生成过程，只有空白/加载状态 |
| **P3** | "final" 全量 reload 导致闪烁 — 消息全部重新获取，DOM 重建 | 视觉闪烁；ToolCard 展开状态、滚动位置丢失 |
| **P4** | ToolCard 与 AI 气泡交错排列 — 按插入顺序而非逻辑分组 | 工具调用视觉上不属于对应回答 |
| **P5** | 流中无实时工具状态 — ToolCard 只在 reload 后出现 | 用户不知道 AI 正在调用什么工具 |
| **P6** | `run_id` TypeScript 类型缺失 — 但代码中已使用 `msg.run_id` | 类型安全风险 |
| **P7** | `CopilotPanel.tsx` 686 行 — 单体组件混杂业务逻辑、SSE、渲染 | 难以维护和测试 |
| **P8** | 切换 session 时流状态残留 — `streamingReasoningText` 和 typewriter ref 未完全清理 | 可能出现上一会话的残留文本 |

---

## 3. 设计决策

### D1: 统一 streaming → 单 AI 消息模型

废除"底部打字机"模式。一个 AI 气泡逐步填充内容：

```
推理阶段 ──→ 工具调用 ──→ 回答生成 ──→ 最终回答
  (reasoning)  (tool_call/result)  (partial_answer)  (final)
```

每个用户轮次 = **一个用户气泡 + 一个 AI 气泡**（含推理/工具/回答）。不再有独立的类型文字块。

### D2: 实时 SSE 渲染，不 reload

每个 SSE 事件到达时即时渲染到 AI 气泡中：

- `reasoning` → 追加推理文本到气泡的推理区域
- `tool_call` → 添加工具卡片（状态: running）
- `tool_result` → 更新工具卡片（状态: done，显示结果）
- `partial_answer` → 追加回答 token 到气泡的回答区域
- `final` → 固化 AI 气泡，停止动画，关闭 EventSource
- `error` → 切换气泡到错误状态

收到 "final" 后**不再全量 reload 消息**。

### D3: 按 run_id 分组工具与 AI 回答

ToolCard 不是独立条目，而是附加在对应 AI 气泡上。渲染时：

```
用户气泡 (run_id: abc)
AI 气泡 (run_id: abc)
  ├── 推理文本
  ├── [可折叠] 工具调用
  │     ├── get_stock_context ✅
  │     ├── analyze_portfolio_risk ✅
  │     └── generate_draft_order ✅
  └── 最终回答 (Markdown)
  └── 建议操作 (NextActions)
```

### D4: 拆分为模块化结构

将 686 行的 CopilotPanel 拆分为：

| 模块 | 职责 | 类型 |
|---|---|---|
| `CopilotPanel.tsx` | 编排层 — 布局、状态连接 | 精简宿主 |
| `useCopilotChat.ts` | **新 Hook** — SSE/Streaming/Session 逻辑 | 核心逻辑 |
| `CopilotMessageItem.tsx` | **新组件** — 单条消息气泡渲染 | 无状态 UI |
| `CopilotToolCard.tsx` | **新组件** — 可折叠工具卡片 | 无状态 UI |
| `CopilotStreamingMessage.tsx` | **新组件** — 实时流式 AI 气泡 | 有状态 UI |

### D5: 补全 `CopilotMessage` 类型

- 前端 `client.ts` 的 `CopilotMessage` 接口加上 `run_id: string | null`

---

## 4. 流状态模型

### 4.1 流式消息状态（新）

```typescript
interface StreamMessage {
  runId: string;
  /** 当前阶段 */
  phase: "reasoning" | "tools" | "answering" | "final" | "error";
  /** 累积的推理文本 */
  reasoningText: string;
  /** 实时工具调用列表 */
  tools: StreamToolCall[];
  /** 累积的部分回答 */
  answerText: string;
  /** final 事件携带的完整 payload */
  finalPayload?: Record<string, unknown>;
  /** 错误信息 */
  error?: string;
}

interface StreamToolCall {
  name: string;
  status: "pending" | "running" | "done" | "failed";
  resultText?: string;
  id: string;
}
```

### 4.2 SSE 事件 → 状态映射

| SSE 事件 | 对 `StreamMessage` 的操作 | phase 转换 |
|---|---|---|
| `skill_trace` | 忽略（已在线程中持久化） | — |
| `reasoning` | `reasoningText += text` | → `"reasoning"` |
| `tool_call` | `tools.push({name, status: "running", id})` | → `"tools"` |
| `tool_result` | `tools[i].status = "done"; tools[i].resultText = ...` | → `"tools"` |
| `partial_answer` | `answerText += text` | → `"answering"` |
| `final` | `finalPayload = payload`; 完成构建 | → `"final"` |
| `error` | `error = msg` | → `"error"` |

### 4.3 流结束后处理

收到 "final" 后：

1. 将 `StreamMessage` 转换为 `CopilotMessage`（user 角色，final_answer 类型）
2. 追加到本地 `messages[]` 列表
3. 清空 `streamMessage`（停止流状态）
4. 后台静默调用 `loadMessages()` 刷新持久化消息（不阻塞 UI 更新，不闪烁）

---

## 5. 实施阶段

### Phase A: 类型 & 基础修复（低风险）

| 步骤 | 文件 | 改动 |
|---|---|---|
| A1 | `frontend/src/api/client.ts` | 添加 `run_id: string \| null` 到 `CopilotMessage` |
| A2 | `frontend/src/types/index.ts` | 确认一致性 |
| A3 | `CopilotPanel.tsx` | `switchSession` 中清理 typewriter ref + `streamingReasoningText` |

### Phase B: 实时 SSE 渲染（核心改动）

| 步骤 | 文件 | 改动 |
|---|---|---|
| B1 | `CopilotPanel.tsx` | 在 `handleSend()` 旁边创建 `StreamMessage` 状态 |
| B2 | `CopilotPanel.tsx` | 重写 SSE 事件处理逻辑（reasoning → tool_call → tool_result → partial_answer → final） |
| B3 | `CopilotPanel.tsx` | 移除底部打字机代码块 |
| B4 | `CopilotPanel.tsx` | 在消息列表末尾插入 `<CopilotStreamingMessage>` |

### Phase C: 组件重构（中风险）

| 步骤 | 文件 | 改动 |
|---|---|---|
| C1 | **新建** `frontend/src/hooks/useCopilotChat.ts` | 提取所有 session/message/streaming 状态和操作 |
| C2 | **新建** `frontend/src/components/features/CopilotMessageItem.tsx` | 提取 `MessageBlock` 渲染逻辑 |
| C3 | **新建** `frontend/src/components/features/CopilotToolCard.tsx` | 提取内联 `ToolCard` 组件 |
| C4 | **新建** `frontend/src/components/features/CopilotStreamingMessage.tsx` | 实时流式 AI 气泡组件 |
| C5 | `CopilotPanel.tsx` | 大幅精简，仅保留编排和布局 |

### Phase D: 消息配对简化

| 步骤 | 文件 | 改动 |
|---|---|---|
| D1 | `CopilotPanel.tsx` | 简化 `pairMessages()`，按 run_id 分组工具和 AI 消息 |

### Phase E: CSS 调整

| 步骤 | 文件 | 改动 |
|---|---|---|
| E1 | `frontend/src/index.css` | 新增 `.msg.ai .phase-badge`、`.msg.ai .tool-summary-inline` 等实时流式指示器样式 |
| E2 | `frontend/src/index.css` | 调整 `.msg.streaming` 动画，使其不干扰正在渲染的实时内容 |

### Phase F: 验证

| 步骤 | 检查项 |
|---|---|
| F1 | 手动冒烟测试 — 发送消息，观察实时气泡渲染 |
| F2 | 会话切换 — 清空流状态，加载历史消息 |
| F3 | 停止按钮 — 关闭 EventSource，展示已接收内容 |
| F4 | 工具卡片 — 实时显示"调用中…" → "完成" 切换 |
| F5 | 错误处理 — SSE error 事件展示错误气泡 |
| F6 | 复制按钮 — 消息复制功能正常 |
| F7 | `lsp_diagnostics` — 所有更改文件无类型/语法错误 |
| F8 | `pytest -q` — 现有后端测试全部通过 |

---

## 6. 文件变更概览

| 文件 | 操作 | 风险 |
|---|---|---|
| `frontend/src/api/client.ts` | 修改 | 低 |
| `frontend/src/hooks/useCopilotChat.ts` | **新增** | 中 |
| `frontend/src/components/features/CopilotMessageItem.tsx` | **新增** | 中 |
| `frontend/src/components/features/CopilotToolCard.tsx` | **新增** | 低 |
| `frontend/src/components/features/CopilotStreamingMessage.tsx` | **新增** | 中 |
| `frontend/src/components/features/CopilotPanel.tsx` | 大幅重构 | 高 |
| `frontend/src/hooks/useAppState.tsx` | 可能清理 | 低 |
| `frontend/src/index.css` | 修改 | 低 |

---

## 7. 执行顺序依赖

```
Phase A (类型/基础)     Phase B (实时SSE)        Phase C (重构)
    A1 types               B1 StreamMessage 状态     C1 useCopilotChat hook
    A2 switch fix          B2 SSE handler 重写       C2 CopilotMessageItem
                           B3 移除底部打字机          C3 CopilotToolCard
                           B4 插入 CopilotStreamingMsg  C4 CopilotStreamingMessage
                                                      C5 精简 CopilotPanel
    ────────────────────────────────────────────────────────────────
    Phase D (配对)         Phase E (CSS)           Phase F (验证)
    D1 pairMessages 简化    E1 流式指示器样式        F1-F8 全面验证
```

- Phase A 和 B 可并行（互不依赖）
- Phase C 依赖 Phase B（需要定型后的 streaming 接口）
- Phase D 依赖 Phase C（需要重构后的组件体系）
- Phase E 可穿插进行
- Phase F 是最终验证关口

---

## 8. 回滚策略

每个 Phase 完成后执行一次提交。若 Phase B/C 引入回归：

1. `git log --oneline -10` 查看最近提交
2. `git revert <commit-hash>` 回滚有问题的 Phase
3. 修复后重新提交

不会出现"改了一半回不去"的状态。

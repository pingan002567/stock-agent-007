# DeerFlow 对话机制与工具调用分析

## 1. 核心发现

### 1.1 DeerFlow 确实有多轮对话能力

DeerFlow 使用 LangGraph 的 `SqliteSaver` 作为 checkpointer，持久化对话状态：

| 组件 | 说明 |
|------|------|
| Checkpointer | `SqliteSaver` (LangGraph 标准持久化) |
| 数据库路径 | `data/deerflow_checkpoints.sqlite3` |
| 数据库大小 | 43MB |
| 总 checkpoint 数 | 807 条 |
| `thread_id` | 使用 `session_id`，同一会话共享 |

### 1.2 Checkpoint 数据结构

```python
checkpoint = {
    'v': int,                    # 版本
    'ts': str,                   # 时间戳
    'id': str,                   # checkpoint ID
    'channel_values': {          # 核心数据
        'messages': list,        # 消息列表
        'thread_data': ...,
        'title': ...,
    },
    'channel_versions': dict,
    'versions_seen': dict,
    'updated_channels': list,
}
```

### 1.3 消息类型

消息使用 LangChain 消息格式：

| 类型 | 说明 |
|------|------|
| `HumanMessage` | 用户消息（包含 envelope JSON） |
| `AIMessage` | AI 回复（可能包含 tool_calls） |
| `ToolMessage` | 工具调用结果 |

## 2. 问题分析

### 2.1 用户报告的问题

用户报告：最新的气泡把历史调用的 tool 都展示出来了。

### 2.2 数据库证据

```sql
-- run_b0c027ab61（第一条消息）
get_worldcup_matches, get_worldcup_analysis, get_worldcup_odds

-- run_fec995b55e（第二条消息）
get_worldcup_matches, get_worldcup_analysis, get_worldcup_odds, web_search
```

第二条消息重新调用了第一条消息的 3 个工具。

### 2.3 Checkpoint 证据

Checkpoint 显示所有工具调用：

```python
['get_worldcup_matches', 'get_worldcup_analysis', 'get_worldcup_odds', 'web_search']
```

但这些工具调用分布在不同的 run 中。

### 2.4 根因

**DeerFlow 的工具调用决策逻辑不考虑之前的工具调用结果。**

即使 checkpoint 中有之前的工具调用结果，DeerFlow 仍然会重新调用这些工具。这可能是：
1. 设计如此 - 确保获取最新数据
2. 工具调用逻辑的局限性

## 3. 前端展示问题

### 3.1 `pairMessages` 函数

前端的 `pairMessages` 函数按 `run_id` 分组展示工具：

```typescript
// 当遇到 final_answer 时，把 pendingTools[rid] 中的所有工具关联到这个 final_answer
if (ev.type === EVENT_FINAL || ev.type === EVENT_ERROR) {
    const tools = pendingTools.get(rid) || [];
    pendingTools.delete(rid);
    out.push({ t: "ai", msg, tools });
}
```

### 3.2 问题

由于 DeerFlow 在同一个 run 中调用了所有工具（包括之前已经调用过的），前端会把这些工具都展示出来。

## 4. 解决方案

### 4.1 方案 A：后端去重（推荐）

在 `copilot_service.py` 中，构建 history 时去重工具调用：

```python
# 从数据库读取上一个 run 的工具调用结果
previous_tools = set()
for msg in self.repo.list_copilot_run_messages(previous_run_id):
    if msg.kind == 'tool_call':
        tool_name = json.loads(msg.payload).get('tool')
        previous_tools.add(tool_name)

# 在 context 中添加历史工具信息
context['previous_tool_calls'] = list(previous_tools)
```

### 4.2 方案 B：前端去重

在 `pairMessages` 中，过滤掉之前已经展示过的工具：

```typescript
// 记录已经展示过的工具
const shownTools = new Set<string>();

// 在处理工具时，只展示新工具
if (!shownTools.has(tool.name)) {
    tools.push(tool);
    shownTools.add(tool.name);
}
```

### 4.3 方案 C：Prompt 注入

在 `prompt_envelope` 中注入历史工具调用信息：

```python
def build_prompt_envelope(*, user_message, skill_trace, context):
    envelope = {
        "envelope_version": "v0.20",
        "user_message": user_message,
        "current_page": context.get("page") or "overview",
        "skill_trace": _trim_skill_trace(skill_trace),
        "condensed_stock_context": _trim_stock_context(context),
        "condensed_page_context": _trim_page_context(context),
        "safety_constraints": SAFE_RUNTIME_CONSTRAINTS,
    }
    # 添加历史工具调用信息
    if context.get("previous_tool_calls"):
        envelope["previous_tool_calls"] = context["previous_tool_calls"]
    return envelope
```

## 5. 验证方法

### 5.1 检查 checkpoint

```python
import sqlite3
import msgpack

conn = sqlite3.connect('data/deerflow_checkpoints.sqlite3')
cursor = conn.cursor()
cursor.execute('''
  SELECT checkpoint FROM checkpoints 
  WHERE thread_id = ? 
  ORDER BY rowid DESC LIMIT 1
''', (session_id,))
row = cursor.fetchone()
if row:
    data = msgpack.unpackb(row[0], raw=False)
    messages = data.get('channel_values', {}).get('messages', [])
    print(f'Messages: {len(messages)}')
```

### 5.2 检查工具调用

```python
tool_calls = []
for msg in messages:
    if isinstance(msg, dict) and 'tool_calls' in msg:
        for tc in msg['tool_calls']:
            if 'name' in tc:
                tool_calls.append(tc['name'])
print(f'Tool calls: {tool_calls}')
```

## 6. 相关文件

| 文件 | 说明 |
|------|------|
| `backend/app_services/copilot_service.py` | Copilot 服务，管理 run 和消息 |
| `backend/agent_runtime/deerflow_client.py` | DeerFlow 客户端适配器 |
| `backend/agent_runtime/prompt_envelope.py` | Prompt 信封构建 |
| `frontend/src/components/features/CopilotPanel.tsx` | 前端消息展示 |
| `data/deerflow_checkpoints.sqlite3` | DeerFlow checkpoint 数据库 |

## 7. 结论

DeerFlow 确实有多轮对话能力，但其工具调用决策逻辑不考虑之前的工具调用结果。这导致在多轮对话中，相同的工具会被重复调用。

解决方案需要在后端或前端进行工具去重，或者在 prompt 中注入历史工具调用信息，让 DeerFlow 知道哪些工具已经调用过。

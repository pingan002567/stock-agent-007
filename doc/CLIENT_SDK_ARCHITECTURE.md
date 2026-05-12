# DeerFlowClient Python SDK 架构文档

> 模块路径: `backend/packages/harness/deerflow/client.py` | 1317 行
> 分析日期: 2026-06-06

---

## 目录

- [1. 概述](#1-概述)
- [2. 架构定位](#2-架构定位)
- [3. 类结构与状态管理](#3-类结构与状态管理)
- [4. Agent 生命周期](#4-agent-生命周期)
- [5. 流式事件系统](#5-流式事件系统)
- [6. 序列化层](#6-序列化层)
- [7. 完整 API 参考](#7-完整-api-参考)
- [8. 依赖关系图](#8-依赖关系图)
- [9. 线程安全分析](#9-线程安全分析)
- [10. 测试架构](#10-测试架构)
- [11. 集成模式](#11-集成模式)

---

## 1. 概述

`DeerFlowClient` 是 DeerFlow 的**嵌入式 Python SDK**，提供进程内直接访问 Agent 全部能力，**无需启动 Gateway API 服务器或 LangGraph Server**。

一句话定位：**Gateway HTTP API 的进程内等价物**——不是 Gateway 的 wrapper，而是与 Gateway 共享同一个 `create_agent()` 工厂、但走独立同步执行路径的并行实现。

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()
for event in client.stream("帮我分析这篇论文", thread_id="my-thread"):
    print(event.type, event.data)
```

---

## 2. 架构定位

### 2.1 双路径架构

```
                        create_agent()  ← 共享核心 LangGraph 图编译
                       ╱               ╲
         sync stream()                   async astream()
              │                               │
     DeerFlowClient.stream()          Gateway worker.run_agent()
              │                               │
     直接 yield StreamEvent           StreamBridge → SSE → HTTP
     (Python Generator)              (asyncio Queue + JSON 序列化)
              │                               │
         进程内调用                      跨网络 HTTP 调用
```

| 维度 | Client (embedded) | Gateway (HTTP) |
|------|-------------------|----------------|
| 执行方式 | `agent.stream()` 同步 | `agent.astream()` 异步 |
| 事件传输 | Generator `yield` 直接返回 | asyncio Queue → JSON → SSE |
| 序列化 | `StreamEvent` dataclass (dict) | `serialize()` → JSON string |
| 适用场景 | 进程内嵌入、脚本、CLI、Jupyter | Web 前端、跨服务调用 |
| 断线重连 | 无（Generator 终止） | StreamBridge Last-Event-ID 重放 |
| 多用户 | 调用方自行管理 | 内置 user_id + auth |

### 2.2 为什么不用 Gateway 的 `run_agent`？

Client 没有复用 Gateway 的 `run_agent`（`runtime/runs/worker.py`），原因有三：

1. **同步 vs 异步**：`run_agent` 是 `async def`，Client 提供同步 `Generator`，避免 asyncio 传染调用方
2. **序列化路径不同**：Gateway 需要 JSON/SSE 序列化，Client 直接返回 Python 数据结构
3. **StreamBridge 不需要**：Gateway 需要 asyncio Queue 解耦生产者/消费者、支持多订阅者、心跳——单进程直接迭代全都不需要

两者通过 `TestGatewayConformance` 保证返回结构一致，但不共享执行代码。

---

## 3. 类结构与状态管理

### 3.1 字段分类

```
DeerFlowClient
│
├── 构造参数（不可变行为配置）
│   ├── config_path: str | None       → AppConfig 加载路径
│   ├── checkpointer: BaseCheckpointSaver | None → 多轮对话状态持久化
│   ├── model_name: str | None        → 默认模型名
│   ├── thinking_enabled: bool        → 推理模式开关
│   ├── subagent_enabled: bool        → 子智能体委派开关
│   ├── plan_mode: bool               → Todo 中间件开关
│   ├── agent_name: str | None        → 自定义智能体名（路由到 SOUL.md）
│   ├── available_skills: set[str] | None → 技能白名单
│   ├── middlewares: list[AgentMiddleware] → 自定义中间件注入
│   └── environment: str | None       → 部署环境标签（Langfuse trace tag）
│
├── 可变状态（决定 Agent 是否重建）
│   ├── _app_config: AppConfig        → 已加载的配置
│   ├── _agent: CompiledStateGraph | None → 编译后的 LangGraph 图（延迟创建）
│   ├── _agent_config_key: tuple | None   → 缓存键（变化时重建 Agent）
│   └── _environment: str | None      → 环境标签
│
└── 公开方法（4 组 × 16 个方法）
    ├── 对话组: stream(), chat()
    ├── 线程组: list_threads(), get_thread()
    ├── 配置组: list_models(), get_model(), list_skills(), get_skill(),
    │          update_skill(), install_skill(), get_mcp_config(), update_mcp_config()
    ├── 记忆组: get_memory(), reload_memory(), clear_memory(),
    │          create_memory_fact(), update_memory_fact(), delete_memory_fact(),
    │          export_memory(), import_memory(), get_memory_config(), get_memory_status()
    └── 文件组: upload_files(), list_uploads(), delete_upload(), get_artifact()
```

### 3.2 Agent 缓存键 (Config Key)

```python
# _ensure_agent() 内部——决定 Agent 是否需要重建
key = (
    model_name,                              # 模型变化
    thinking_enabled,                        # 推理开关变化
    is_plan_mode,                            # 计划模式变化
    subagent_enabled,                        # 子智能体开关变化
    agent_name,                              # 智能体身份变化
    frozenset(available_skills),             # 技能白名单变化
)

if self._agent is not None and self._agent_config_key == key:
    return  # 命中缓存，跳过重建
```

设计意图：编译 LangGraph 图 + 生成系统提示词成本高，只有在行为参数真正改变时才重建。这是一种 **memoization 模式**。

`reset_agent()` 强制清空缓存——用于外部变化（如技能安装、模型配置更新）后的刷新。

---

## 4. Agent 生命周期

### 4.1 完整创建流程

```
_ensure_agent(config)
│
├── 1. 检查 _agent_config_key 缓存
│   └── 命中 → 直接返回（跳过后续 7 步）
│
├── 2. 获取工具集
│   └── _get_tools(model_name, subagent_enabled)
│       └── get_available_tools() → sandbox + builtin + community + MCP
│           工具由 config.yaml 的 tools 段定义，按 group 过滤
│
├── 3. 延迟工具过滤
│   └── _assemble_deferred(tools, enabled)
│       ├── 识别 MCP 工具 → 从模型 schema 中移除完整定义
│       ├── 注入 tool_search 工具 → Agent 可运行时按需激活
│       └── 返回 (final_tools, deferred_setup)
│
├── 4. 创建模型实例
│   └── create_chat_model(name, thinking_enabled, attach_tracing=False)
│       └── attach_tracing=False 是关键——追踪 callback 在 stream() 中
│           注入到 graph 根级别，不在 model 级别重复绑定
│
├── 5. 构建中间件链
│   └── _build_middlewares(config, model_name, agent_name, custom_middlewares, deferred_setup)
│       └── 18 个中间件按序装配：
│           ThreadData → Uploads → Sandbox → DanglingToolCall → Guardrail
│           → ToolErrorHandling → DeferredToolFilter → Summarization → Todo
│           → TokenUsage → Title → Memory → ViewImage → SubagentLimit
│           → LoopDetection → SafetyFinishReason → DynamicContext → Clarification
│
├── 6. 生成系统提示词
│   └── apply_prompt_template(subagent_enabled, agent_name, skills, deferred_names)
│       └── 静态骨架 + 技能名称/简介注入 + 日期/记忆动态占位（运行时填充）
│
├── 7. 附加 Checkpointer
│   └── if checkpointer is None → get_checkpointer() 自动获取默认
│       └── SQLite（默认）或 PostgreSQL
│
└── 8. 编译 LangGraph 图
    └── create_agent(model, tools, middleware, system_prompt, state_schema, checkpointer)
        └── 返回 CompiledStateGraph → 存入 self._agent
```

### 4.2 状态机

```
    __init__()
        │
        ▼
    _agent = None ──────────────────────────────┐
    _agent_config_key = None                     │
        │                                        │
        │ 首次 stream() / chat()                 │ reset_agent()
        ▼                                        │
    _ensure_agent()                              │
        │                                        │
        ├── 缓存命中 → 直接使用                    │
        │                                        │
        └── 缓存未命中 → 编译新 Agent ─────────────┘
                │
                ▼
        _agent = CompiledStateGraph
        _agent_config_key = (model, thinking, plan, subagent, agent_name, skills)
                │
                │ stream() / chat() 多次调用
                ▼
            正常服务（config_key 不变则复用）
                │
                │ 模型切换 / 技能变更 / 配置更新
                ▼
        _ensure_agent() → config_key 变化 → 重新编译
```

---

## 5. 流式事件系统

### 5.1 事件类型 (StreamEvent)

```python
@dataclass
class StreamEvent:
    type: Literal["values", "messages-tuple", "custom", "end"]
    data: dict[str, Any]
```

| 事件类型 | 触发时机 | data 结构 | 说明 |
|---------|---------|----------|------|
| `messages-tuple` | 每个消息块产生时 | `{type:"ai","content":"<delta>","id":"msg_xxx"}` | AI 文本 **delta**（不是完整文本！） |
| `messages-tuple` | 工具调用时 | `{type:"ai","content":"","tool_calls":[...],"id":"msg_xxx"}` | 工具调用请求 |
| `messages-tuple` | 工具结果返回时 | `{type:"tool","content":"...","name":"bash","tool_call_id":"..."}` | 工具执行结果 |
| `values` | 每个 graph node 完成后 | `{title, messages:[...], artifacts:[...]}` | 完整状态快照 |
| `custom` | 透传自定义事件 | `{...}` | 由自定义中间件/工具发出 |
| `end` | 流程结束时 | `{usage:{input_tokens,output_tokens,total_tokens}}` | 累计 token 消耗 |

### 5.2 流式管道

```
agent.stream(state, config, stream_mode=["values", "messages", "custom"])
        │
        ├── mode="messages" (token 级增量)
        │   ├── AIMessageChunk(text="你") → _ai_text_event()
        │   │   └── StreamEvent("messages-tuple", {type:"ai", content:"你", id:"msg_1"})
        │   │
        │   ├── AIMessageChunk(text="好") → _ai_text_event()
        │   │   └── StreamEvent("messages-tuple", {type:"ai", content:"好", id:"msg_1"})
        │   │   ↑ 注意：同一个 id，调用方按 id 累积 "你"+"好"="你好"
        │   │
        │   ├── AIMessageChunk(tool_calls=[{name:"bash", args:{...}}])
        │   │   └── StreamEvent("messages-tuple", {type:"ai", tool_calls:[...], id:"msg_2"})
        │   │
        │   └── ToolMessage(name="bash", content="file1.txt\nfile2.txt")
        │       └── StreamEvent("messages-tuple", {type:"tool", name:"bash", content:"..."})
        │
        ├── mode="values" (完整状态快照，每个 node 完成后)
        │   └── StreamEvent("values", {title:"xxx", messages:[完整序列化], artifacts:[...]})
        │       └── 已通过 messages 模式发出的消息 → 跳过（去重）
        │
        ├── mode="custom" (透传)
        │   └── StreamEvent("custom", data={...})
        │
        └── 循环结束后:
            └── StreamEvent("end", {usage:{input_tokens: 1200, output_tokens: 300, total_tokens: 1500}})
```

### 5.3 去重机制

三组集合协同工作：

```python
seen_ids: set[str]              # values 模式已处理的消息 ID（跨轮去重）
streamed_ids: set[str]          # messages 模式已发出的消息 ID（跨模式去重）
counted_usage_ids: set[str]     # 已统计 token 的消息 ID（防重复计数）
```

- `messages` 模式产出的 AI 文本 delta 加入 `streamed_ids`
- `values` 模式遍历消息时，已存在于 `streamed_ids` 的 ID **跳过序列化**，只捕获 usage
- 同一消息 ID 的 usage_metadata 只在首次到达时累加

### 5.4 chat() vs stream()

```python
# chat() 是 stream() 的便利封装
def chat(self, message, thread_id=None):
    chunks: dict[str, list[str]] = {}  # 按 msg_id 分组累积 delta
    last_id = ""
    for event in self.stream(message, thread_id=thread_id):
        if event.type == "messages-tuple" and event.data.get("type") == "ai":
            delta = event.data.get("content", "")
            if delta:
                chunks.setdefault(msg_id, []).append(delta)
                last_id = msg_id
    return "".join(chunks.get(last_id, ()))  # 返回最后一个 AI 消息的完整文本
```

**关键约定**：`chat()` 返回**最后一个** AI 消息的文本——中间的规划/草稿消息被丢弃。需要完整对话历史时，应使用 `stream()` 或 `get_thread()`。

---

## 6. 序列化层

### 6.1 消息序列化

```python
_serialize_message(msg) → dict

# 输入: LangChain Message 对象
# 输出: {"type": "ai"|"tool"|"human"|"system", "content": ..., "id": ...}

AIMessage    → {"type":"ai", "content":"...", "tool_calls":[...], "usage_metadata":{...}, "id":"..."}
ToolMessage  → {"type":"tool", "content":"...", "name":"bash", "tool_call_id":"call_xxx", "id":"..."}
HumanMessage → {"type":"human", "content":"...", "id":"..."}
SystemMessage→ {"type":"system", "content":"...", "id":"..."}
其他         → {"type":"unknown", "content":"str(msg)", "id":"..."}
```

### 6.2 文本提取 (_extract_text)

处理 LangChain 的 `content` 字段（可能是 `str`、`list[str]`、`list[dict]`）：

```python
content = "hello"                              → "hello"
content = ["你", "好"]                          → "你好"（短 chunk 拼接）
content = [{"type":"text","text":"段落1"}, ...]  → "段落1\n段落2"（换行连接）
content = [{"type":"image_url",...}, "text"]   → "text"（跳过非文本块）
```

### 6.3 additional_kwargs 增量发送

```python
_unsent_additional_kwargs(msg_id, kwargs) → delta_dict | None

# 只发送与上次相比有变化的字段，避免重复传输 reasoning_content 等大字段
sent_additional_kwargs_by_id: dict[str, dict]  # 按消息 ID 记录已发送的 kwargs
```

### 6.4 工具调用序列化

```python
_serialize_tool_calls(tool_calls) → [
    {"name": "bash", "args": {"command": "ls"}, "id": "call_abc123"},
    {"name": "read_file", "args": {"path": "/mnt/..."}, "id": "call_def456"},
]
```

---

## 7. 完整 API 参考

### 7.1 构造函数

```python
DeerFlowClient(
    config_path: str | None = None,       # config.yaml 路径，None=默认解析
    checkpointer=None,                    # LangGraph checkpointer，多轮对话必需
    *,
    model_name: str | None = None,        # 默认模型名（可被 stream() kwargs 覆盖）
    thinking_enabled: bool = True,        # 启用推理模式
    subagent_enabled: bool = False,       # 启用子智能体委派
    plan_mode: bool = False,              # 启用 TodoList 中间件
    agent_name: str | None = None,        # 自定义智能体名
    available_skills: set[str] | None = None,  # 技能白名单
    middlewares: Sequence[AgentMiddleware] | None = None,  # 自定义中间件
    environment: str | None = None,       # 部署环境标签
)
```

### 7.2 对话 API

```python
# 流式对话（token 级增量）
def stream(
    self, message: str, *,
    thread_id: str | None = None,
    **kwargs,                     # model_name, thinking_enabled, plan_mode,
) -> Generator[StreamEvent]: ... # subagent_enabled, recursion_limit

# 同步对话（返回最终文本）
def chat(self, message: str, *, thread_id: str | None = None, **kwargs) -> str: ...
```

### 7.3 线程管理

```python
def list_threads(self, limit: int = 10) -> dict:
    """返回 {"thread_list": [{thread_id, created_at, updated_at, title, ...}]}"""

def get_thread(self, thread_id: str) -> dict:
    """返回 {"thread_id": str, "checkpoints": [{checkpoint_id, ts, values, ...}]}"""
```

### 7.4 模型管理

```python
def list_models(self) -> dict:
    """返回 ModelsListResponse schema: {"models": [...], "token_usage": {...}}"""

def get_model(self, name: str) -> dict | None:
    """返回 ModelResponse schema 或 None"""
```

### 7.5 技能管理

```python
def list_skills(self, enabled_only: bool = False) -> dict:
    """返回 SkillsListResponse schema: {"skills": [{name, description, category, enabled, ...}]}"""

def get_skill(self, name: str) -> dict | None:
    """返回 SkillResponse schema 或 None"""

def update_skill(self, name: str, *, enabled: bool) -> dict:
    """启/禁用技能，返回更新后的 SkillResponse，抛 ValueError/OSError"""

def install_skill(self, skill_path: str | Path) -> dict:
    """安装 .skill 压缩包，返回 SkillInstallResponse: {success, skill_name, message}"""
```

### 7.6 MCP 配置

```python
def get_mcp_config(self) -> dict:
    """返回 McpConfigResponse schema: {"mcp_servers": {name: {enabled, type, command, ...}}}"""

def update_mcp_config(self, mcp_servers: dict[str, dict]) -> dict:
    """更新 MCP 配置并热重载，返回更新后的 McpConfigResponse"""
```

### 7.7 记忆管理

```python
def get_memory(self) -> dict:         # 获取当前记忆数据
def reload_memory(self) -> dict:      # 从文件重新加载记忆
def clear_memory(self) -> dict:       # 清空所有记忆
def export_memory(self) -> dict:      # 导出记忆（备份/迁移）
def import_memory(self, memory_data: dict) -> dict:  # 导入记忆

def create_memory_fact(self, content, category="context", confidence=0.5) -> dict:
def update_memory_fact(self, fact_id, content=None, category=None, confidence=None) -> dict:
def delete_memory_fact(self, fact_id: str) -> dict:

def get_memory_config(self) -> dict:  # 记忆系统配置
def get_memory_status(self) -> dict:  # 配置 + 数据
```

### 7.8 文件操作

```python
def upload_files(self, thread_id: str, files: list[str | Path]) -> dict:
    """上传文件，自动转换 PDF/PPT/Excel/Word 为 Markdown
       返回 UploadResponse schema: {success, files: [{filename, size, path, virtual_path, ...}], message}"""

def list_uploads(self, thread_id: str) -> dict:
    """列出上传文件: {files: [...], count: N}"""

def delete_upload(self, thread_id: str, filename: str) -> dict:
    """删除上传文件（含路径遍历检查）: {success, message}"""
```

### 7.9 产物

```python
def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]:
    """读取 Agent 生成的文件，返回 (文件字节, MIME 类型)
       path: 虚拟路径，如 "mnt/user-data/outputs/report.pdf" """
```

### 7.10 生命周期

```python
def reset_agent(self) -> None:
    """强制下次调用时重建 Agent（技能/配置变更后使用）"""
```

---

## 8. 依赖关系图

```
DeerFlowClient (client.py)
│
├── deerflow.agents.lead_agent.agent
│   ├── _build_middlewares()          ← 18 个中间件链装配
│   ├── _assemble_deferred()          ← MCP 工具延迟加载
│   └── apply_prompt_template()       ← 系统提示词生成
│
├── deerflow.agents.thread_state      ← ThreadState (LangGraph 状态 schema)
│
├── deerflow.config
│   ├── app_config                    ← AppConfig 模型配置 (get/reload)
│   ├── agents_config                 ← AGENT_NAME_PATTERN 校验
│   ├── extensions_config             ← MCP + Skill 状态 (get/reload)
│   └── paths                         ← 虚拟路径解析 (Paths)
│
├── deerflow.models.factory           ← create_chat_model()
│
├── deerflow.tools                    ← get_available_tools()
│
├── deerflow.skills.storage           ← 技能发现与加载
│
├── deerflow.tracing                  ← LangSmith/Langfuse 追踪注入
│
├── deerflow.runtime
│   ├── checkpointer                  ← 状态持久化
│   └── user_context                  ← 用户身份解析
│
├── deerflow.uploads.manager          ← 7 个文件操作函数
│   ├── ensure_uploads_dir()          ├── get_uploads_dir()
│   ├── list_files_in_dir()           ├── enrich_file_listing()
│   ├── claim_unique_filename()       ├── delete_file_safe()
│   └── upload_virtual_path() / upload_artifact_url()
│
├── deerflow.agents.memory.updater    ← 8 个记忆操作函数
│   ├── get_memory_data()             ├── reload_memory_data()
│   ├── clear_memory_data()           ├── import/export_memory_data()
│   └── create/update/delete_memory_fact()
│
└── deerflow.utils.file_conversion    ← PDF/PPT/Excel/Word → Markdown
```

---

## 9. 线程安全分析

### 9.1 现状

`DeerFlowClient` **不是线程安全的**。问题点：

```
_agent              ← 读写无锁
_agent_config_key   ← 读写无锁
stream() 内部:
  seen_ids           ← 每次调用新建的局部变量，同一实例并发调用会混淆
  streamed_ids       ← 同上
  counted_usage_ids  ← 同上
```

### 9.2 正确使用模式

| 模式 | 代码 | 适用场景 |
|------|------|---------|
| **每请求一实例** | `client = DeerFlowClient(checkpointer=cp); client.stream(...)` | Web 服务（推荐） |
| **全局锁保护** | `with lock: client.stream(...)` | 简单 CLI 工具 |
| **每线程一实例** | `threading.local()` 存储 | 多线程后台任务 |
| **asyncio 隔离** | `await asyncio.to_thread(client.stream, ...)` + 每线程独立 Client | 异步 Web 框架 |

---

## 10. 测试架构

### 10.1 测试金字塔

```
                    ┌─────────────────┐
                    │ test_client_live│  ← 真实 LLM，需 API key
                    │   (CI 跳过)      │     金字塔顶，少而精
                    └────────┬────────┘
                    ┌────────┴────────┐
                    │ test_client_e2e │  ← 真实 LLM + 真实模块
                    │ (806行, CI部分)  │     文件系统隔离
                    └────────┬────────┘
              ┌─────────────┴─────────────┐
              │    test_client.py         │
              │    (3234行, CI 始终运行)    │  ← Mock 一切，全覆盖
              │                           │
              │  ├── TestClientInit       │
              │  ├── TestStreamEvents     │
              │  ├── TestChat             │
              │  ├── TestGatewayConformance│ ← ★ 核心约束
              │  ├── TestListModels       │
              │  ├── TestSkills           │
              │  ├── TestMcpConfig        │
              │  ├── TestMemory           │
              │  ├── TestUploads          │
              │  └── TestArtifactHardening│
              └───────────────────────────┘
```

### 10.2 TestGatewayConformance —— 架构约束

这是 Client 架构的**核心质量关卡**：

```python
class TestGatewayConformance:
    """验证 Client 返回 dict 能通过 Gateway Pydantic Response Model 校验。
    如果 Client 返回字段缺失/类型错误，Pydantic ValidationError → CI 失败。"""

    def test_list_models(self):
        result = client.list_models()
        parsed = ModelsListResponse(**result)   # ← Gateway Pydantic 模型
        assert parsed.models[0].name == "test-model"

    def test_get_model(self):
        result = client.get_model("test-model")
        parsed = ModelResponse(**result)        # ← 同上

    def test_list_skills(self):
        result = client.list_skills()
        parsed = SkillsListResponse(**result)

    def test_install_skill(self):
        result = client.install_skill(archive_path)
        parsed = SkillInstallResponse(**result)

    # ... 覆盖所有返回 dict 的方法
```

Gateway 的 Pydantic Response Models 定义在：
- `app/gateway/routers/models.py` → `ModelsListResponse`, `ModelResponse`
- `app/gateway/routers/skills.py` → `SkillsListResponse`, `SkillResponse`, `SkillInstallResponse`
- `app/gateway/routers/mcp.py` → `McpConfigResponse`
- `app/gateway/routers/memory.py` → `MemoryConfigResponse`, `MemoryStatusResponse`
- `app/gateway/routers/uploads.py` → `UploadResponse`

---

## 11. 集成模式

### 11.1 最小化示例

```python
from deerflow.client import DeerFlowClient
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("chat.db")
client = DeerFlowClient(
    config_path="config.yaml",
    checkpointer=checkpointer,
    model_name="gpt-4o",
)

# 单轮对话
print(client.chat("Hello!"))

# 多轮流式
for event in client.stream("帮我写一个快速排序", thread_id="thread-1"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"], end="", flush=True)
```

### 11.2 Web 服务集成 (FastAPI + SSE)

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.post("/chat/stream")
async def chat_stream(user_id: str, message: str):
    def generate():
        for event in client.stream(message, thread_id=user_id):
            yield f"data: {json.dumps({'type': event.type, 'data': event.data}, ensure_ascii=False)}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 11.3 CLI 聊天机器人

```python
def run_cli():
    tid = None
    while True:
        msg = input("You: ").strip()
        if msg == "/new":
            tid = None; continue
        if msg == "/quit":
            break
        print("AI: ", end="", flush=True)
        for event in client.stream(msg, thread_id=tid):
            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                print(event.data.get("content", ""), end="", flush=True)
            elif event.type == "end":
                print(f"\n[tokens: {event.data['usage']['total_tokens']}]")
```

### 11.4 多用户服务

```python
class MultiUserService:
    def __init__(self, client: DeerFlowClient):
        self.client = client
        self._user_threads: dict[str, str] = {}

    def chat(self, user_id: str, message: str):
        tid = self._user_threads.setdefault(user_id, str(uuid.uuid4()))
        return self.client.chat(message, thread_id=tid)

    def new_thread(self, user_id: str):
        self._user_threads[user_id] = str(uuid.uuid4())
```

### 11.5 配置热更新

```python
# 1. 运行时安装技能
client.install_skill("./my-custom-skill.skill")

# 2. 启用特定技能
client.update_skill("my-custom-skill", enabled=True)

# 3. 切换模型
client.reset_agent()
# 下次 stream() 调用会用新模型 + 新技能重建 Agent

# 4. 更新 MCP 服务器
client.update_mcp_config({
    "github": {"enabled": True, "type": "stdio", "command": "npx", ...}
})
# 自动重置 Agent，下次调用生效
```

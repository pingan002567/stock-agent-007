# Tech Stack Decisions

本文档记录了 Stock Workbench 后端的关键技术栈决策，是项目架构的**强依赖**。

所谓「强依赖」意味着：每个决策都有明确的背景和选择理由，后续演进必须在其约束下进行——除非有充分理由重新评估（并更新本文档）。

---

## 1. Agent Runtime: DeerFlowClient

### 决策

Agent 循环（LLM 调用 + 工具选择 + 工具执行 + 结果综合）统一使用 `deerflow.client.DeerFlowClient`，**不手写 LangGraph StateGraph**。

### 背景

v0.8~v0.20 期间，Direct 模式（`WORKBENCH_AI_MODE=direct`）使用手写 `langgraph_agent.py`（依赖 langchain-core、langgraph、langchain-openai），Embedded 模式使用 `DeerFlowClient`。两条路径维护成本高、事件格式不统一。

### 选择理由

1. **上游官方推荐**：deer-flow 是 DeerFlow 的官方 Python SDK，已内部依赖 langchain-core / langgraph，无需项目再直接依赖
2. **工具注册**：通过 `config.yaml` 的 `use:` 反射即可注册 Workbench 工具，无需手动创建 `StructuredTool` 列表
3. **事件格式统一**：Direct 和 Embedded 两种模式都输出 `StreamEvent`（LangGraph SSE 协议），减少事件映射复杂度
4. **记忆/Checkpointer**：内置 `MemorySaver` 支持，thread_id 即可恢复对话状态

### 约束

- 不能绕过 `DeerFlowClient` 直接调用 LangGraph API
- 如需自定义 `system_prompt`，通过 `render_prompt_envelope()` 嵌入到 `message` 参数中传递
- 不开放 `subagent_enabled` / `plan_mode`（已锁定为 False）

### 实现

- `backend/agent_runtime/deerflow_client.py`：`DeerFlowClientAdapter` 封装，统一 stream 入口
- `backend/agent_runtime/deerflow_config.py`：运行时生成最小 config.yaml（Direct 模式）
- `WORKBENCH_AI_MODE=direct` 和 `WORKBENCH_DEERFLOW_MODE=embedded` 最终都通过 `DeerFlowClient` 执行

---

## 2. 工具注册: use: 反射 + Bridge 注入

### 决策

工具通过 DeerFlow `config.yaml` 的 `use:` 反射注册为 `StructuredTool` 实例，运行时委托给 `WorkbenchToolBridge.execute()`。

### 背景

最初（v0.8~v0.20）使用 `langchain_tools.py` + `create_workbench_tools(bridge)` 工厂函数手动创建工具列表。每新增一个工具需要在工厂函数里加一行。DeerFlow 迁移后改为自动发现。

### 选择理由

1. **零手动注册**：新增工具只需在 `tools.py` 里加一个 `_tool()` 调用，config 生成器和 DeerFlowClient 自动发现
2. **DeerFlow 原生**：`get_available_tools()` 通过 `resolve_variable(cfg.use, BaseTool)` 加载，与 DeerFlow 现有工具机制一致
3. **延迟绑定**：`_bridge` 在 bootstrap 时注入，工具在调用时才 resolve bridge，不产生 import-time 副作用

### 约束

- `tools.py` 中的工具必须是模块级 `StructuredTool` 实例（不是函数）
- 工具输入必须使用 Pydantic `BaseModel`，由 `_tool()` 的 `args_schema` 参数指定
- 工具名必须与 `config.yaml` 中 `name` 一致
- 所有工具最终调用 `WorkbenchToolBridge.execute()`，没有独立实现路径

### 实现

- `backend/agent_runtime/tools.py`：模块级 `StructuredTool` 实例 + `_bridge` 引用 + `init_workbench_tools()` 注入函数
- `backend/bootstrap.py`：调用 `workbench_tools.init_workbench_tools(tool_bridge)` 注入
- `backend/agent_runtime/deerflow_config.py`：`_build_tool_configs()` 通过 `get_all_workbench_tools()` 自动生成 tools section

### 新增工具步骤

1. 在 `tools.py` 中定义输入模型（继承 `BaseModel`）
2. 在 `tools.py` 中用 `_tool(name, desc, schema, authority)` 创建实例
3. 重启服务（config 重新生成，`DeerFlowClient` 自动发现）

---

## 3. 配置生成: 运行时动态 YAML

### 决策

Direct 模式的 `config.yaml` 不在源码中维护，而是在 bootstrap 时由 `generate_config()` 从环境变量 + 工具注册表动态生成。

### 背景

DeerFlow 期望通过 `config.yaml` 配置 models、tools、sandbox、skills 等。但 Workbench 的模型配置来自运行时环境变量（`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`WORKBENCH_AI_MODEL`），随部署环境变化。静态配置文件不可行。

### 选择理由

1. **零环境泄漏**：`config.yaml` 写入 `data/` 目录（已 gitignore），不进入 repo
2. **开箱即用**：用户只需设置环境变量，不需要手动创建 DeerFlow 配置
3. **自动同步**：新增工具 → `tools.py` → `get_all_workbench_tools()` → 下次重启自动注册
4. **可复写**：`WORKBENCH_DEERFLOW_CONFIG_PATH` 环境变量可覆盖，Embedded 模式仍然使用用户提供的配置

### 约束

- 生成的 config 不包含 `extensions_config.json`、`skills/` 等 DeerFlow 附加文件
- `sandbox.use = deerflow.sandbox.local:LocalSandboxProvider, allow_host_bash: false`（固定）
- 仅用于 Direct 模式；Embedded 模式使用 DeerFlow 自身的 config 解析路径

### 实现

- `backend/agent_runtime/deerflow_config.py`：`generate_config()` → 写 `data/deerflow_generated_config.yaml`
- 在 `DeerFlowClientAdapter.from_env()` 的 Direct 模式分支中调用

---

## 4. 记忆/多轮对话

### 决策

对话历史通过 LangGraph `checkpointer`（`MemorySaver`）管理，以 `thread_id` 为维度自动恢复。**不使用** 手动传递 `history` 参数。

### 背景

v0.20 引入 `copilot_session` / `copilot_message` 持久化 + `history` 参数的传递链。DeerFlow 迁移后，线程状态由 checkpointer 自动管理。

### 选择理由

1. **消除重复**：不再需要手动从 SQLite 加载历史 → 序列化为 `AIMessage`/`HumanMessage` → 传入 agent loop
2. **底层可靠**：LangGraph `MemorySaver` 基于 checkpointer 协议，与 `DeerFlowClient` 原生集成
3. **线程隔离**：`thread_id` 天然隔离不同会话，无需额外的 session context 管理

### 约束

- `checkpointer` 在 `DeerFlowClient` 初始化时传入（Direct 模式使用 `MemorySaver()`）
- `thread_id` = `run_id`（当前每次请求一个 run_id，后续应改为 `session_id` 以跨请求保持上下文）
- Embedded 模式使用 DeerFlow 默认的 checkpointer（从 `get_checkpointer()` 获取）

---

## 5. 权限边界 (Authority Levels)

### 决策

工具按授权级别分为 A2（研究）、A3（组合/风控）、A4（拟单）、A5（真实交易），在工具定义时通过 `_tool()` 的 `authority` 参数固定。运行时由 `WorkbenchToolBridge.execute()` 校验。

### 背景

项目从一开始就设计了权限层次。这是架构的核心约束，不可绕过。

### 选择理由

1. **声明式**：权限在工具定义时就固定，不在运行时动态决定
2. **审计可追溯**：每次工具执行都会写 `tool_execution` ledger，包含权限上下文
3. **LLM 不可绕过**：即使 LLM 请求 A5 工具，bridge 也会拒绝；LLM 没有权限提升能力

### 约束

- A2 工具：研究类（行情、历史、情报、监控、策略、回测、报告）
- A3 工具：组合/风控类（持仓、风险评估、策略配置、决策日志、待办）
- A4 工具：拟单类（生成草案、审查）
- A5 工具：真实下单（始终 blocked）
- 不能通过 `config.yaml` 或设置页改变工具权限级别

---

## 6. 删除的模块（2026-05-27）

以下模块在 DeerFlow 迁移后被删除，由 `tools.py` + `DeerFlowClient` 替代：

| 删除文件 | 替代方案 |
|---|---|
| `backend/agent_runtime/langchain_tools.py` | `backend/agent_runtime/tools.py`（模块级 `StructuredTool`） |
| `backend/agent_runtime/langgraph_agent.py` | `DeerFlowClient.stream()`（内部基于 langgraph） |

---

## 依赖关系（2026-05-27 后）

```
pyproject.toml
  └── deerflow-harness @ git+https://github.com/bytedance/deer-flow.git
        ├── langchain-core        (transitive)
        ├── langgraph             (transitive)
        ├── langchain-openai      (transitive)
        └── ...
  └── openai>=2.37.0             (直接依赖，给用户侧使用)
  └── fastapi/uvicorn/pydantic

backend/bootstrap.py
  └── WorkbenchToolBridge
        └── workbench_tools.init_workbench_tools()  ← bridge 注入
              └── tools.py 的 _bridge 引用
  └── DeerFlowClientAdapter.from_env()
        └── DeerFlowClient(config_path=generate_config())
              └── 自动发现 tools.py 的 StructuredTool
```

---

## 7. DeerFlow Platform Capabilities & Recommended Practices

### 7.1 What DeerFlow Is

DeerFlow is an open-source **super agent harness** — a LangGraph-powered orchestration framework from ByteDance. It is **not** a chatbot or an agent itself; it is the **runtime** that wires together models, tools, memory, sub-agents, sandboxes, and skills into a production agent.

> Upstream: https://github.com/ByteDance-Seed/deerflow

**Our project currently uses DeerFlowClient as a thin adapter.** The sections below document what the framework _can_ do beyond our current usage, so future decisions have a complete reference.

### 7.2 Architecture (Official)

```
┌─────────────────────────────────────────────┐
│                  LeadAgent                    │
│  (primary orchestrator, single LLM instance) │
├─────────────────────────────────────────────┤
│  Plan Node → SubAgentDispatch → ToolExec     │
│        → Memory Inject → Response            │
├─────────────────────────────────────────────┤
│  Sub-agents │ Memory │ Sandbox │ Skills      │
└─────────────────────────────────────────────┘
```

Core concepts:

| Concept | Role |
|---|---|
| **LeadAgent** | Main agent — delegates to sub-agents, calls tools, manages conversation flow |
| **SubAgent** | Specialized agent for a subtask (code gen, research, etc.) — receives its own context |
| **Memory** | Persistent fact store — auto-extracts, debounces, and injects into prompt |
| **Sandbox** | Code execution environment — local subprocess or Docker container |
| **Skill** | Hot-pluggable capability — loaded/unloaded dynamically via config |
| **Tool** | Function exposed to LLM — discovered via `use:` reflection or registered directly |
| **Checkpointer** | LangGraph checkpoint saver for conversation history persistence |
| **Thread ID** | Per-conversation isolation key — all state scoped to thread |

### 7.3 Core Capabilities Detail

#### 7.3.1 LeadAgent & Sub-Agents
- **LeadAgent** is the top-level agent that interprets user intent, decomposes tasks, delegates to sub-agents, and assembles the final response.
- **Sub-agents** are independently configured LLM instances (can use different models, tools, system prompts than the lead).
- Sub-agents produce structured artifacts (code, analysis, plans) that get fed back to LeadAgent.
- **Plan mode** (`AgentMode.PLAN`) decomposes complex requests before execution — the plan node runs first, then execution follows the plan.

**Official recommendation:** Use sub-agents for any multi-step reasoning task (planning, research, code generation). Avoid stuffing all logic into a single agent prompt.

#### 7.3.2 Memory System
- **Fact extraction**: Automatically extracts "facts" (key-value assertions) from conversation history.
- **Debounced persistence**: Writes to store only after a configurable debounce interval (default enabled).
- **Context injection**: Relevant facts injected into system prompt on each turn — keeps long-running sessions grounded.
- **Multiple store backends**: DuckDB (default), SQLite, or custom implementations.
- **Scope**: Per-thread, configurable namespace isolation.

**Official recommendation:** Keep memory enabled but set a reasonable debounce window (5-30s). Don't disable it — it's the primary mechanism for cross-turn consistency.

#### 7.3.3 Tool System
- **Automatic discovery**: Tools registered via `use:` directive in config — DeerFlow scans for `StructuredTool` instances in those modules.
- **Python callables**: Any function can be wrapped as a tool with type-annotated parameters.
- **MCP tools**: External MCP servers can be mounted as tool providers.
- **Access control**: Per-tool permission flags (allow list, deny list).

**Official recommendation:** Prefer `use:` reflection over manual registration. Keep tool return values structured (dict/JSON) — raw strings break the LLM's ability to parse results.

#### 7.3.4 Sandbox
- **Local sandbox**: Runs code in a subprocess with resource limits (CPU, memory, timeouts).
- **Docker sandbox**: Runs code in an isolated container with network/filesystem restrictions.
- **Code languages**: Python by default; extensible to shell, JavaScript, etc.
- **Output capture**: stdout/stderr are captured and attached to the tool result as structured fields.

**Official recommendation:** Always enable sandbox for user-supplied code execution. Use Docker sandbox in multi-tenant deployments.

#### 7.3.5 Streaming
- **Protocol**: LangGraph SSE (Server-Sent Events) — standardised streaming protocol.
- **Events**: `on_chain_start`, `on_chain_end`, `on_tool_start`, `on_tool_end`, `on_agent_start`, `on_agent_end`, token-level deltas.
- **Scalability**: Stateless between events — suitable for server-sent streaming to frontends.
- **Fallback**: Synchronous `invoke()` always available for non-streaming usage.

#### 7.3.6 Context Summarization
- **Trigger**: When total message tokens exceed a configurable threshold.
- **Behavior**: Compresses older messages into a natural-language summary, truncates raw messages beyond the threshold.
- **Preserved**: Tool results and structured outputs are kept verbatim — only conversational turns get summarized.

### 7.4 Configuration System

Configuration is YAML-based and structured as follows:

```yaml
agent:
  model:
    provider: openai           # or anthropic, google, deepseek, ollama, etc.
    model: gpt-4o
    temperature: 0.7
  memory:
    enabled: true
    store: duckdb
    debounce_seconds: 10
  sandbox:
    enabled: true
    type: local                # or docker
    timeout: 30
  tools:
    use:
      - workbench.tools        # auto-discovers StructuredTool classes
      - app.tools.custom
  sub_agents:
    file_agent:
      model: gpt-4o-mini
      system_prompt: "You are a file operation specialist."
      tools:
        use:
          - app.tools.file_ops
```

**Official recommendation:** Keep all config in a single YAML file. Use environment variable interpolation (`${VAR_NAME}`) for secrets. Avoid scattering config in Python code.

### 7.5 Official Recommended Practices Summary

| Practice | Our Status | Notes |
|---|---|---|
| Use sub-agents for multi-step reasoning | ❌ Not yet | We rely on a single agent — could add for planning/research |
| Enable memory with debounce | ✅ Yes | DeerFlowClient enables it by default |
| Tool auto-discovery via `use:` | ✅ Yes | Our `tools.py` is auto-discovered |
| Sandbox for code execution | ❌ Not yet | Security hardening opportunity |
| YAML single-file config | ✅ Yes | `generate_config()` produces one YAML |
| Streaming SSE for UI | ✅ Used | Real-time AI Chat via EventSource (reasoning/tool_call/partial_answer/final) |
| Thread ID for isolation | ✅ Yes | `session_id` is used as thread ID |
| Plan mode for complex tasks | ❌ Not yet | Could be activated for multi-step analysis |
| Skill plugins | ❌ Not used | DeerFlow ships 10+ built-in skills |
| MCP tool bridging | ❌ Not yet | Could bridge to external tool servers |

### 7.6 DeerFlow Upstream Relationship

We are not forking DeerFlow — our `DeerFlowClientAdapter` wraps it with project-specific defaults:

```
deerflow  (upstream package)
    ↑
DeerFlowClient       ← thin wrapper (connect / disconnect / invoke / stream)
    ↑
DeerFlowClientAdapter  ← adds tool bridge, config generation
    ↑
bootstrap.py
```

**Upgrading:** When `deerflow` releases a new version, the adapter generally requires zero changes. If breaking changes occur, they should be absorbed in `DeerFlowClientAdapter`, not leaked into business logic.

---

## 演进原则

1. **不走回头路**：不再回到手写 LangGraph 状态机。如果 DeerFlowClient 无法满足需求，优先向上游贡献
2. **工具注册表自动发现**：不新增 `create_workbench_tools()` 风格的工厂函数
3. **检查点优先**：对话记忆使用 checkpointer，不手动管理 `copilot_message` 的历史回放
4. **配置文件不提交**：运行时生成的 `data/deerflow_generated_config.yaml` 不进入版本控制
5. **利用框架而非绕过**：在采纳 DeerFlow 新能力（sub-agent / plan mode / sandbox）之前，先评估官方推荐做法，而非手写替代方案

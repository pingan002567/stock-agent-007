# Tool + MCP 完全依赖 DeerFlow 原生系统 —— 设计规划

> 项目: stock-agent-001 | 日期: 2026-06-06
> 验证依据: DeerFlow v2.0 源码 (tools/, mcp/, config/, reflection/)

---

## 1. DeerFlow 原生标准（源码验证）

### 1.1 Tool 注册标准

**配置格式** (`config/tool_config.py`):

```yaml
tools:
  - name: get_stock_context        # ★ 必需: 唯一名
    group: workbench               # ★ 必需: 工具组
    use: backend.agent_runtime.tools:get_stock_context  # ★ 必需: package.module:variable
    max_results: 5                 # ★ 可选: 额外参数 (model_extra)
```

**加载机制** (`tools/tools.py` L44-176):

```
get_available_tools(groups, model_name, subagent_enabled)
│
├── 1. 按 group 过滤 tool configs
├── 2. 检查 sandbox 模式 (host bash 默认禁用)
├── 3. resolve_variable(cfg.use, BaseTool) → 反射加载
│      └── import_module("backend.agent_runtime.tools")
│      └── getattr(module, "get_stock_context")
│      └── isinstance check → BaseTool ✅
├── 4. 加入 built-in tools (present_file, ask_clarification, task...)
├── 5. 加入 MCP tools (从 extensions_config.json 加载)
├── 6. 加入 ACP tools (invoke_acp_agent)
├── 7. 去重: 按 tool.name 去重，config 注册的优先
└── 8. 返回 list[BaseTool]
```

### 1.2 Tool 代码标准

**社区工具模式** (`community/tavily/tools.py`):

```python
from langchain.tools import tool

@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.    ← docstring → LLM 看到的 description

    Args:                  ← Google-style docstring
        query: The query to search for.
    """
    # ...业务逻辑...
    return json.dumps(results)  # 返回 JSON 字符串
```

**内置工具模式** (`tools/builtins/view_image_tool.py`):

```python
@tool("view_image", parse_docstring=True)
def view_image_tool(
    image_path: Annotated[str, ...],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: Runtime,              # ← 注入运行时上下文
) -> ToolMessage | Command:        # ← 可返回 ToolMessage 或 Command
```

**关键约定**：
- 用 `@tool(name, parse_docstring=True)` 装饰器
- docstring → LLM 看到的工具描述
- `Args:` 段 → LLM 看到的参数描述
- 返回 `str`（推荐）或 `ToolMessage` / `Command`
- 异步工具自动包装同步 wrapper (`make_sync_tool_wrapper`)

### 1.3 MCP 标准

**配置格式** (`extensions_config.json`):

```json
{
  "mcpServers": {
    "stock-data": {
      "enabled": true,
      "type": "stdio",
      "command": "python",
      "args": ["-m", "stock_mcp_server"],
      "env": {"API_KEY": "$STOCK_API_KEY"}
    },
    "http-search": {
      "enabled": true,
      "type": "http",
      "url": "https://api.example.com/mcp",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$MCP_CLIENT_ID",
        "client_secret": "$MCP_CLIENT_SECRET"
      }
    }
  },
  "skills": {
    "stock-researcher": {"enabled": true}
  }
}
```

**加载机制** (`mcp/cache.py`):

```
initialize_mcp_tools()
│
├── 读取 extensions_config.json
├── 过滤 enabled MCP servers
├── 对每个 server: 建立 session (stdio/SSE/HTTP)
├── 获取 tool list → 包装为 BaseTool
├── tag_mcp_tool(tool) → 标记为 MCP 来源
├── 缓存 (mtime-based 失效)
└── 返回 list[BaseTool]
```

**MCP 服务器类型**：
| type | 通信 | 适用场景 |
|------|------|---------|
| stdio | 子进程 stdin/stdout | 本地 Python/Node MCP server |
| http | HTTP POST | 远程 REST API |
| sse | Server-Sent Events | 远程流式服务 |

### 1.4 工具分组标准

```yaml
tool_groups:
  - name: web            # 网页搜索/抓取
  - name: file:read      # 文件读取
  - name: file:write     # 文件写入
  - name: bash           # 命令执行
  - name: workbench      # ★ 你的: Workbench 工具
```

Agent 创建时可按 group 过滤工具：

```python
tools = get_available_tools(groups=["workbench"])
```

### 1.5 工具延迟加载 (Tool Search)

```yaml
tool_search:
  enabled: true    # MCP 工具不直接绑定到模型
```

启用后，MCP 工具只在系统提示词中列出名称，Agent 通过 `tool_search` 工具按需激活完整 schema。节省初始 token。

---

## 2. 当前项目状态

### 2.1 已有的 ✅

| 项 | 状态 | 说明 |
|----|------|------|
| Tool 注册 | ✅ | `deerflow_config.py` 通过 `use:` 反射注册 38 个工具 |
| Tool 代码 | ✅ | `tools.py` 使用 `StructuredTool.from_function()` |
| tool_groups | ⚠️ | 只有 1 个组 `workbench`，无权限分级 |
| extensions_config | ❌ | 不存在，无法管理 skill 状态和 MCP |
| MCP | ❌ | 无 MCP 服务器 |
| Tool Search | ❌ | 未启用 |
| 去重 | ⚠️ | DeerFlow 自动去重，但 38 个工具一次性加载 |

### 2.2 需要改造

| 项 | 当前 | 目标 |
|----|------|------|
| tool_groups | 1 组 `workbench` | 4 组: a2-research, a3-risk, a4-planner, a5-blocked |
| extensions_config.json | 不存在 | 创建，管理 skill + MCP 状态 |
| 工具注册路径 | `backend.agent_runtime.tools:tool_name` | ✅ 保持不变 |
| 工具代码 | `StructuredTool.from_function()` | 加入 `parse_docstring` 或显式 description |
| MCP | 不存在 | 预留接口，未来可接 AKShare/数据源 MCP |

---

## 3. 实施步骤

### Step 1: 创建 `extensions_config.json`

```json
{
  "mcpServers": {},
  "skills": {
    "stock-researcher":    {"enabled": true},
    "risk-officer":        {"enabled": true},
    "strategy-analyst":    {"enabled": true},
    "rebalance-planner":   {"enabled": true},
    "stock-monitor":       {"enabled": true},
    "report-writer":       {"enabled": true}
  }
}
```

### Step 2: 改造 `deerflow_config.py` — 权限分组 + skills

```python
def generate_config(target_dir="data"):
    config = {
        "models": [_build_model_config()],
        "sandbox": {...},
        # ★ 按权限分级
        "tool_groups": [
            {"name": "a2-research"},
            {"name": "a3-risk"},
            {"name": "a4-planner"},
            {"name": "a5-blocked"},
        ],
        # ★ 每个工具归入对应权限组
        "tools": _build_tool_configs(),
        # ★ skills 路径
        "skills": {
            "path": "skills",
            "container_path": "/mnt/skills",
        },
        # ★ MCP 延迟加载（未来用）
        "tool_search": {"enabled": False},
        # ★ 工具输出保护
        "tool_output": {
            "enabled": True,
            "externalize_min_chars": 12000,
        },
    }
```

### Step 3: 工具按权限分组

```python
# deerflow_config.py

A2_TOOLS = [
    "get_stock_context", "get_daily_history", "search_stock_intel",
    "add_watchlist_item", "remove_watchlist_item",
    "get_monitor_events", "get_monitor_rules", "evaluate_monitor_rules",
    "list_strategies", "get_backtest_result",
    "list_report_templates", "generate_report", "get_report_quality",
]

A3_TOOLS = [
    "get_portfolio_snapshot", "upsert_holding",
    "analyze_portfolio_risk", "get_active_risk_policy",
    "list_risk_policies", "evaluate_policy_risk",
    "run_strategy_backtest", "list_pre_trade_reviews", "list_paper_orders",
    "get_paper_portfolio", "analyze_paper_performance", "create_paper_portfolio_snapshot",
    "list_decision_journal", "get_decision_journal_entry", "summarize_decision_outcomes",
    "list_review_inbox", "summarize_review_inbox",
    "dismiss_inbox_item", "snooze_inbox_item", "mark_inbox_item_done",
]

A4_TOOLS = [
    "generate_draft_order", "list_rebalance_drafts", "get_rebalance_draft",
    "confirm_rebalance_draft", "reject_rebalance_draft", "create_pre_trade_review",
]

A5_BLOCKED = ["place_real_order"]

TOOL_GROUP_MAP = {}
for t in A2_TOOLS: TOOL_GROUP_MAP[t] = "a2-research"
for t in A3_TOOLS: TOOL_GROUP_MAP[t] = "a3-risk"
for t in A4_TOOLS: TOOL_GROUP_MAP[t] = "a4-planner"
for t in A5_BLOCKED: TOOL_GROUP_MAP[t] = "a5-blocked"

def _build_tool_configs():
    configs = []
    for tool in get_all_workbench_tools():
        configs.append({
            "name": tool.name,
            "group": TOOL_GROUP_MAP.get(tool.name, "a2-research"),
            "use": f"backend.agent_runtime.tools:{tool.name}",
        })
    return configs
```

### Step 4: 按 group 加载工具（权限控制）

```python
# adapter 中按 authority_level 过滤工具组
AUTHORITY_GROUPS = {
    "A2": ["a2-research"],
    "A3": ["a2-research", "a3-risk"],
    "A4": ["a2-research", "a3-risk", "a4-planner"],
}

# get_available_tools 支持 groups 参数
groups = AUTHORITY_GROUPS.get(authority_level, ["a2-research"])
tools = get_available_tools(groups=groups, subagent_enabled=...)
```

### Step 5: 未来 MCP 扩展——股票数据源

```json
// extensions_config.json — 未来扩展
{
  "mcpServers": {
    "akshare-data": {
      "enabled": true,
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "stock_mcp_server"],
      "env": {}
    },
    "market-news": {
      "enabled": true,
      "type": "http",
      "url": "https://news-api.example.com/mcp"
    }
  },
  "skills": { ... }
}
```

MCP 工具自动被 DeerFlow 加载、缓存、标记、去重。

---

## 4. 完整配置模板 (deerflow_generated_config.yaml)

```yaml
# 运行时生成的完整配置
models:
  - name: gpt-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o

sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false

# ★ tool_groups: 权限分级
tool_groups:
  - name: a2-research
  - name: a3-risk
  - name: a4-planner
  - name: a5-blocked

# ★ tools: 38 个工具，每个归入权限组
tools:
  - name: get_stock_context
    group: a2-research
    use: backend.agent_runtime.tools:get_stock_context
  - name: get_portfolio_snapshot
    group: a3-risk
    use: backend.agent_runtime.tools:get_portfolio_snapshot
  - name: generate_draft_order
    group: a4-planner
    use: backend.agent_runtime.tools:generate_draft_order
  - name: place_real_order
    group: a5-blocked
    use: backend.agent_runtime.tools:place_real_order
  # ... 其余 34 个工具

# ★ skills: DeerFlow 原生发现 + 注入
skills:
  path: skills
  container_path: /mnt/skills

# ★ MCP 延迟加载（预留）
tool_search:
  enabled: false

# ★ 工具输出保护
tool_output:
  enabled: true
  externalize_min_chars: 12000
```

---

## 5. 与 extensions_config.json 的关系

```
deerflow_generated_config.yaml        extensions_config.json
─────────────────────────────────     ────────────────────────
models: [...]                         mcpServers: { ... }
tools: [...] (38 个注册)               skills: { stock-researcher: {enabled: true}, ... }
tool_groups: [...]                    
sandbox: ...                          
skills: { path: "skills" }           ← skills 路径在这里
                                      ← skill enabled 状态在这里
                                      

两者互补:
  config.yaml → 静态配置（模型、工具注册、sandbox）
  extensions_config.json → 动态配置（MCP 服务器、skill 启/禁状态）
```

---

## 6. 工具发现全链路

```
1. DeerFlowClient.__init__(config_path)
   └── AppConfig.from_file(config_path)
       └── tools: [38 个 ToolConfig {name, group, use}]
       └── tool_groups: [4 个]

2. get_available_tools(groups=["a2-research", "a3-risk"])
   ├── 过滤: 只保留 group 在列表中的工具
   ├── resolve_variable("backend.agent_runtime.tools:get_stock_context")
   │   └── import_module → getattr → StructuredTool 实例
   ├── 加入 built-in tools
   ├── 加入 MCP tools (从 extensions_config.json + cache)
   └── 去重 → 返回 list[BaseTool]

3. filter_tools_by_skill_allowed_tools(tools, skills)
   └── union(allowed-tools from all loaded skills)
   └── 只保留在 allowed-tools 中的工具

4. create_agent(model, tools, ...)
   └── LangGraph 图编译 → tools 绑定到模型
```

---

## 7. 验证清单

```bash
# 1. extensions_config.json
cat extensions_config.json | python -m json.tool
# 预期: 含 mcpServers + skills 段

# 2. 生成 config
python -c "
from backend.agent_runtime.deerflow_config import generate_config
path = generate_config()
print(f'Config: {path}')
import yaml
with open(path) as f:
    cfg = yaml.safe_load(f)
print(f'Tools: {len(cfg[\"tools\"])}')
print(f'Groups: {[g[\"name\"] for g in cfg[\"tool_groups\"]]}')
print(f'Skills: {cfg.get(\"skills\", {})}')"

# 3. 按组加载
python -c "
from deerflow.tools import get_available_tools
a2 = get_available_tools(groups=['a2-research'])
a3 = get_available_tools(groups=['a2-research', 'a3-risk'])
print(f'A2 tools: {len(a2)}')
print(f'A2+A3 tools: {len(a3)}')"

# 4. 端到端: Agent 只看到对应权限的工具
# A2 权限用户 → 只能看到 a2-research 组工具
# A4 权限用户 → 能看到 a2+a3+a4 组工具
```

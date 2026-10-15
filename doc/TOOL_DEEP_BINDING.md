# Workbench 工具与 DeerFlow 深度绑定方案

> 项目: stock-agent-001 | 分析日期: 2026-06-06

---

## 1. 当前绑定架构

```
DeerFlowClient.stream()
│
├── config.yaml 工具注册:
│   use: backend.agent_runtime.tools:get_stock_context
│
├── DeerFlow 反射加载 → StructuredTool 实例
│   └── 调用时 → _bridge.execute(name, kwargs, authority)   ← L1 执行
│       └── WorkbenchToolBridge.execute()
│           ├── ExecutionPolicy.decide()  → blocked/needs_confirmation/allowed
│           ├── PermissionGuard.require()
│           ├── _handlers[name](arguments)
│           └── tool_execution_service.record() → ledger
│
└── Adapter._map_and_execute_tools()                        ← L2 重复执行
    └── tool_call 事件被拦截 → tool_bridge.execute() → 再写一次 ledger
```

**核心问题：同一个 tool_call 被执 行了两次，ledger 双写。**

---

## 2. 当前限制

| 问题 | 影响 |
|------|------|
| **双写 ledger** | tool_bridge 执行一次 + adapter 拦截再执行一次，产生两条 tool_execution 记录 |
| **模块级全局 `_bridge`** | `tools.py: _bridge: Any = None` 是模块单例，多线程不安全 |
| **Schema 不同步** | `tool_bridge.py` 的 `ToolSpec.input_schema` 手写 dict vs `tools.py` 的 Pydantic `args_schema`，可能不一致 |
| **Pydantic 校验丢失** | tool_bridge 的 `execute()` 接收裸 `dict`，LangChain StructuredTool 的 Pydantic 校验白做了 |
| **权限分散** | `ExecutionPolicy.decide()` 在 tool_bridge，`PermissionGuard.require()` 在 adapter 里又做一次 |
| **DeerFlow 不可见 ledger** | tool_execution 表对 DeerFlow Agent 完全黑盒，多轮中无法引用历史执行 |

---

## 3. 深度绑定方案

### 核心思路

工具直接作为 DeerFlow Native Tool 自包含执行全流程：
**Pydantic 校验 → 权限 → 策略 → 业务 → ledger → 结果**

Adapter 的 `_map_and_execute_tools()` 简化为纯事件透传，不再拦截工具执行。

```
改造前:  DeerFlow 执行 tool → bridge → adapter 又执行一遍
改造后:  DeerFlow 执行 tool → bridge（全流程，一次完成）→ adapter 纯透传
```

### Step 1：工具函数内置完整流程

```python
# backend/agent_runtime/tools.py

def _tool(name, description, args_schema, authority) -> StructuredTool:
    def _run(**kwargs: Any) -> str:
        # 1. Pydantic 校验（LangChain 自动完成 args_schema(**kwargs)）
        validated = args_schema(**kwargs)

        # 2. 获取 bridge（ContextVar 线程安全注入）
        bridge = _bridge_ctx.get()
        if bridge is None:
            raise RuntimeError("Workbench bridge not initialised")

        # 3. 权限检查
        bridge.permission_guard.require(current_level, authority, name)

        # 4. 策略判断
        policy = bridge.execution_policy.decide(name)
        if policy.mode == ExecutionMode.BLOCKED:
            raise PermissionDenied(policy.reason)

        # 5. 执行业务
        result = bridge._handlers[name](validated.model_dump())

        # 6. 写 ledger
        bridge._record_execution(tool=name, status="succeeded", result=result, ...)

        # 7. 返回 JSON（LLM 可解析）
        return json.dumps(result, ensure_ascii=False, default=str)

    return StructuredTool.from_function(
        func=_run, name=name, description=description,
        args_schema=args_schema, return_direct=False,
    )
```

### Step 2：Bridge 通过 ContextVar 注入

```python
# backend/agent_runtime/tools.py
import contextvars
_bridge_ctx: contextvars.ContextVar = contextvars.ContextVar("workbench_bridge")

def set_bridge(bridge) -> None:
    _bridge_ctx.set(bridge)
```

### Step 3：Adapter 去掉工具拦截层

```python
# backend/agent_runtime/deerflow_client.py — adapter.stream()

async def stream(self, ...):
    # 注入 bridge context
    set_bridge(self.tool_bridge)

    raw_stream = self.client.stream(...)
    async for raw_event in self._iterate_raw_stream(raw_stream):
        # 纯事件映射，不再拦截执行
        for event in mapper.map(raw_event):
            yield event
```

### Step 4：Config 自动生成 tool schema

```python
# backend/agent_runtime/deerflow_config.py

def _build_tool_configs() -> list[dict]:
    configs = []
    for tool in get_all_workbench_tools():
        configs.append({
            "name": tool.name,
            "group": "workbench",
            "use": f"backend.agent_runtime.tools:{tool.name}",
            "description": tool.description,  # 自动同步
        })
    return configs
```

### Step 5：tool_bridge 精简为纯业务层

去掉 `execute()` 中的权限/策略判断（已内聚到工具函数），保留：
- `_handlers` 业务方法（38 个具体实现）
- `has_tool()` 查询接口
- `_record_execution()` ledger 写入
- `ToolSpec` 元数据

---

## 4. 改造前后对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 工具执行次数 | 2 次（DeerFlow + adapter） | 1 次（DeerFlow 内部） |
| ledger 写入 | 双写 | 单写 |
| Bridge 引用 | 模块级全局 `_bridge` | ContextVar 线程安全 |
| 权限判断 | tool_bridge + adapter 两处 | 工具函数内一处 |
| Pydantic 校验 | 丢失（bridge 收 dict） | 保留（LangChain 自动） |
| Schema 来源 | tool_bridge ToolSpec + tools.py 手动对齐 | Pydantic args_schema 单一真相源 |
| DeerFlow 感知 ledger | 不可见 | 结果 JSON 包含 evidence_refs |
| adapter `_map_and_execute_tools()` | 60 行 | 删除 |
| 未知工具处理 | 透传 SSE，不写 ledger | 不变 |

### 保持不变

- stub 模式直接调用 tool_bridge（不走 DeerFlow）
- `place_real_order` 永远 blocked
- `ExecutionPolicy.NEEDS_CONFIRMATION` 确认流程
- 工具别名映射（`strategy_backtest → run_strategy_backtest`）

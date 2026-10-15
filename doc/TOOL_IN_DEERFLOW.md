# 工具执行完全交给 DeerFlow —— 实施指南

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 目标

工具执行从 adapter 拦截层完全移到 DeerFlow 内部，消除双写：

```
改造前: DeerFlow内部执行 → adapter又拦截执行一遍 （双写ledger）
改造后: DeerFlow内部执行（全流程）→ adapter纯事件透传 （单写ledger）
```

---

## 涉及的 4 个文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `tools.py` | `_tool` 工厂重写 + 全局变量→ContextVar | 核心改动 |
| `deerflow_client.py` | 删 `_map_and_execute_tools`，改名映射独立 | 大幅精简 |
| `tool_bridge.py` | 精简 `execute()`，去掉重复权限 | stub 模式保留 |
| `bootstrap.py` | `init_workbench_tools` 一行适配 | 极小 |

---

## 改动 1：`backend/agent_runtime/tools.py`

### 1.1 顶部新增 ContextVar

```python
# 替换第 27 行的 _bridge: Any = None
import contextvars
import json

_bridge_ctx: contextvars.ContextVar = contextvars.ContextVar("workbench_bridge")


def set_bridge(bridge: Any) -> None:
    """每次 DeerFlowClient.stream() 调用前注入 bridge。

    ContextVar 自动隔离不同协程/线程，比模块级全局变量安全。
    """
    _bridge_ctx.set(bridge)


def _get_bridge() -> Any:
    bridge = _bridge_ctx.get(None)
    if bridge is None:
        raise RuntimeError("Workbench bridge not initialised — call set_bridge() first")
    return bridge
```

### 1.2 重写 `_tool` 工厂（第 194-219 行 → 替换）

```python
from backend.app_services.execution_policy import ExecutionMode

def _tool(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    authority: AuthorityLevel,
) -> StructuredTool:
    """创建自包含工具——DeerFlow 直接执行，adapter 不拦截。

    工具内部完成: Pydantic校验 → ExecutionPolicy → PermissionGuard → 业务 → ledger
    返回 JSON 字符串给 LLM，同时写 tool_execution 表。
    """

    def _run(**kwargs: Any) -> str:
        validated = args_schema(**kwargs)            # 1. Pydantic 校验
        bridge = _get_bridge()                       # 2. ContextVar 获取
        spec = bridge._specs[name]                   # 3. ToolSpec 元数据
        arguments = validated.model_dump()           # 4. dict 参数

        # 5. ExecutionPolicy 策略判断
        policy = bridge.execution_policy.decide(name)

        if policy.mode == ExecutionMode.BLOCKED:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs,
                error=policy.reason,
            )
            return json.dumps({"error": policy.reason, "status": "blocked"}, ensure_ascii=False)

        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            result = {"status": "needs_confirmation", "reason": policy.reason, "next_action": policy.next_action}
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs, result=result,
            )
            return json.dumps(result, ensure_ascii=False)

        # 6. PermissionGuard 权限检查
        bridge.permission_guard.require(authority, spec.required_authority, name)

        # 7. 执行业务
        try:
            result = bridge._handlers[name](arguments)
        except Exception as exc:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="failed",
                authority_level=spec.required_authority.value,
                arguments=arguments, evidence_refs=spec.evidence_refs, error=str(exc),
            )
            raise

        # 8. 写 ledger（一次！）
        bridge._record_execution(
            tool=name, domain=spec.domain, status="succeeded",
            authority_level=spec.required_authority.value,
            arguments=arguments, evidence_refs=spec.evidence_refs, result=result,
        )

        return json.dumps(result, ensure_ascii=False, default=str)

    _run.__name__ = name
    return StructuredTool.from_function(
        func=_run, name=name, description=description,
        args_schema=args_schema, return_direct=False,
    )
```

### 1.3 保留兼容函数

```python
# 替换第 30-33 行
def init_workbench_tools(bridge: Any) -> None:
    """兼容旧代码：设置 ContextVar。stub 模式也通过此函数注入。"""
    set_bridge(bridge)
```

### 1.4 `get_all_workbench_tools()` 不变

工具实例名称不变，DeerFlow config 注册 `use: backend.agent_runtime.tools:tool_name` 不需要任何改动。

---

## 改动 2：`backend/agent_runtime/deerflow_client.py`

### 2.1 `stream()` 方法改造（第 541-554 行 → 替换）

```python
            stream_started = False
            try:
                # ── 注入 bridge context（每次 stream 调用前设置）──
                from backend.agent_runtime.tools import set_bridge
                if self.tool_bridge:
                    set_bridge(self.tool_bridge)

                async for raw_event in self._iterate_raw_stream(raw_stream):
                    stream_started = True
                    self._clear_degraded()
                    # ── 纯事件映射，不拦截执行 ──
                    # 工具已在 DeerFlow 内部通过 StructuredTool._run() 执行完毕
                    for event in mapper.map(raw_event):
                        # 工具别名映射（仅影响前端展示）
                        event = self._apply_alias(event)
                        # 收集 evidence_refs
                        if event["type"] == "tool_result":
                            refs = event["payload"].get("evidence_refs", [])
                            for ref in refs:
                                if ref not in tool_evidence_refs:
                                    tool_evidence_refs.append(ref)
                        yield event
```

### 2.2 别名映射独立为小函数

```python
    @staticmethod
    def _apply_alias(event: dict) -> dict:
        """工具名别名映射——只影响前端展示，不改变执行。"""
        alias_map = {
            "strategy_backtest": "run_strategy_backtest",
            "get_strategy_list": "list_strategies",
            "get_strategy_backtest": "get_backtest_result",
        }
        if event.get("type") == "tool_call":
            tool_name = event["payload"].get("tool", "")
            if tool_name in alias_map:
                event["payload"]["tool"] = alias_map[tool_name]
        return event
```

### 2.3 删除 `_map_and_execute_tools`（第 724-799 行，75行）

整个方法删除。

---

## 改动 3：`backend/agent_runtime/tool_bridge.py`

### 3.1 精简 `execute()`（第 570-673 行 → 精简）

```python
def execute(self, name, arguments, authority_level, *, run_id=None, task_id=None, call_id=None, source_mode=None):
    """纯执行入口——仅 stub 模式使用。

    DeerFlow 模式下工具函数内置全流程，不经过此处。
    """
    if name not in self._handlers:
        raise KeyError(name)

    spec = self._specs[name]
    args = arguments or {}

    # stub 模式保留策略判断（因为不走 DeerFlow Guardrails）
    if source_mode == "stub":
        policy = self.execution_policy.decide(name)
        if policy.mode == ExecutionMode.BLOCKED:
            raise PermissionDenied(policy.reason)
        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            return {"status": "needs_confirmation", "reason": policy.reason}

    result = self._handlers[name](args)

    if source_mode == "stub":
        self._record_execution(
            tool=name, domain=spec.domain, status="succeeded",
            authority_level=spec.required_authority.value,
            arguments=args, task_id=task_id, run_id=run_id, call_id=call_id,
            source_mode=source_mode, evidence_refs=spec.evidence_refs, result=result,
        )

    return {"tool": name, "result": result, "evidence_refs": spec.evidence_refs}
```

---

## 改动 4：`backend/bootstrap.py`

### 第 234 行 → 不变

```python
workbench_tools.init_workbench_tools(tool_bridge)  # 内部改为 set_bridge()
```

---

## 执行流对比

### 改造前

```
DeerFlow Agent 调用 get_stock_context
│
├── StructuredTool._run() → _bridge.execute("get_stock_context", ...)   ← 执行1
│   └── tool_bridge: 权限 + 策略 + 业务 + ledger（写1）
│
├── DeerFlow 产出 tool_call 事件
│
└── adapter._map_and_execute_tools() 拦截
    └── tool_bridge.execute("get_stock_context", ...)                   ← 执行2（重复）
        └── tool_bridge: 权限 + 策略 + 业务 + ledger（写2）
```

### 改造后

```
DeerFlow Agent 调用 get_stock_context
│
├── StructuredTool._run() → 权限 + 策略 + 业务 + ledger（写1次） ★ 全流程
│
├── DeerFlow 产出 tool_call 事件
│
└── adapter → mapper.map() → 别名映射 → 直接 yield ★ 纯透传
```

---

## 验证清单

- [ ] `tools.py`: `_tool` 工厂内置全流程，`_bridge` 改为 ContextVar
- [ ] `deerflow_client.py`: `_map_and_execute_tools` 删除，stream() 中纯事件映射
- [ ] `tool_bridge.py`: `execute()` 精简，只保留 stub 模式需要的逻辑
- [ ] `bootstrap.py`: 无改动或一行适配
- [ ] stub 模式: 功能不变（走 `_stub_stream` → `tool_bridge.execute()`）
- [ ] 单元测试: tool 函数独立可测（mock bridge via ContextVar）
- [ ] 集成验证: `SELECT tool, COUNT(*) FROM tool_execution GROUP BY tool, call_id HAVING COUNT(*) > 1` → 0 行
- [ ] Smoke: `uv run python scripts/deerflow_smoke.py` → SSE 事件正常

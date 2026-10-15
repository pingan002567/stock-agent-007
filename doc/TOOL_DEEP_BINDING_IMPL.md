# 工具与 DeerFlow 深度绑定——实施指南

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 问题回顾

当前工具被**执行两次**：

```
DeerFlow 内部执行:
  StructuredTool._run() → bridge.execute(name, kwargs, authority)
    → ExecutionPolicy.decide + PermissionGuard + 业务 + ledger  ← 第1次

Adapter 拦截再执行:
  _map_and_execute_tools() → bridge.execute(name, kwargs, authority)
    → ExecutionPolicy.decide + PermissionGuard + 业务 + ledger  ← 第2次（重复）
```

根因：工具函数 (`tools.py` `_tool`) 只做委托，adapter (`deerflow_client.py` `_map_and_execute_tools`) 又拦截 tool_call 事件重复执行。

---

## 实施步骤

### Step 1：改造 `tools.py` — 工具函数内置全流程

**文件**: `backend/agent_runtime/tools.py`

```python
# ── 新增: ContextVar 替代模块级全局 _bridge ──
import contextvars
import json

_bridge_ctx: contextvars.ContextVar = contextvars.ContextVar("workbench_bridge")


def set_bridge(bridge: Any) -> None:
    """注入 bridge，线程/协程安全。在每次 DeerFlowClient.stream() 调用前设置。"""
    _bridge_ctx.set(bridge)


def _get_bridge() -> Any:
    """获取当前上下文的 bridge。"""
    bridge = _bridge_ctx.get(None)
    if bridge is None:
        raise RuntimeError(
            "Workbench bridge not initialised — call set_bridge() "
            "before using workbench tools."
        )
    return bridge


# ── 改造: _tool 工厂 —— 内置全流程 ──

from backend.app_services.execution_policy import ExecutionMode

def _tool(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    authority: AuthorityLevel,
) -> StructuredTool:
    """创建自包含的 DeerFlow Native Tool。

    工具内部完成:
      Pydantic 校验 → ExecutionPolicy → PermissionGuard → 业务 → ledger → 返回

    DeerFlow 直接使用此工具，adapter 不再拦截重复执行。
    """

    def _run(**kwargs: Any) -> str:
        # 1. Pydantic 校验（LangChain 自动完成 args_schema(**kwargs)）
        validated = args_schema(**kwargs)

        # 2. 获取 bridge（ContextVar 注入）
        bridge = _get_bridge()
        spec = bridge._specs[name]

        # 3. ExecutionPolicy 判断
        policy = bridge.execution_policy.decide(name)

        if policy.mode == ExecutionMode.BLOCKED:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=validated.model_dump(),
                evidence_refs=spec.evidence_refs,
                error=policy.reason,
            )
            raise PermissionError(policy.reason)

        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            result = {
                "status": "needs_confirmation",
                "reason": policy.reason,
                "next_action": policy.next_action,
            }
            bridge._record_execution(
                tool=name, domain=spec.domain, status="blocked",
                authority_level=spec.required_authority.value,
                arguments=validated.model_dump(),
                evidence_refs=spec.evidence_refs,
                result=result,
            )
            return json.dumps(result, ensure_ascii=False, default=str)

        # 4. PermissionGuard 检查
        bridge.permission_guard.require(authority, spec.required_authority, name)

        # 5. 执行业务逻辑
        try:
            result = bridge._handlers[name](validated.model_dump())
        except Exception as exc:
            bridge._record_execution(
                tool=name, domain=spec.domain, status="failed",
                authority_level=spec.required_authority.value,
                arguments=validated.model_dump(),
                evidence_refs=spec.evidence_refs,
                error=str(exc),
            )
            raise

        # 6. 写 ledger（同步，DeerFlow 可见）
        bridge._record_execution(
            tool=name, domain=spec.domain, status="succeeded",
            authority_level=spec.required_authority.value,
            arguments=validated.model_dump(),
            evidence_refs=spec.evidence_refs,
            result=result,
        )

        # 7. 返回 JSON 字符串（LangChain 工具返回 str 最通用）
        return json.dumps(result, ensure_ascii=False, default=str)

    _run.__name__ = name
    return StructuredTool.from_function(
        func=_run,
        name=name,
        description=description,
        args_schema=args_schema,
        return_direct=False,  # 不直接返回，LLM 看到结果后继续推理
    )


# ── 删除: 旧的 init_workbench_tools 和 _bridge 全局变量 ──
# 注意: 如果 stub 模式仍需全局 bridge，保留兼容函数:

def init_workbench_tools(bridge: Any) -> None:
    """兼容旧代码：同时设置 ContextVar 用于 DeerFlow 模式。"""
    set_bridge(bridge)
```

### Step 2：精简 `tool_bridge.py` — 去掉 `execute()` 中的权限判断

**文件**: `backend/agent_runtime/tool_bridge.py`

`execute()` 方法保留给 stub 模式使用（因为 stub 不走 DeerFlow 工具函数），但去掉 `PermissionGuard.require()` 调用（已内聚到工具函数）。

```python
# execute() 改为纯执行（stub 模式专用）:
def execute(self, name, arguments, authority_level, *, run_id=None, task_id=None, call_id=None, source_mode=None):
    """纯执行入口，用于 stub 模式。
    
    DeerFlow 模式下工具函数内置全流程，不经过此处。
    """
    if name not in self._handlers:
        raise KeyError(name)
    spec = self._specs[name]

    # stub 模式仍需策略判断
    if source_mode in {"stub", "copilot"}:
        policy = self.execution_policy.decide(name)
        if policy.mode == ExecutionMode.BLOCKED:
            raise PermissionDenied(policy.reason)
        if policy.mode == ExecutionMode.NEEDS_CONFIRMATION:
            return {"status": "needs_confirmation", "reason": policy.reason}

    result = self._handlers[name](arguments or {})
    self._record_execution(tool=name, domain=spec.domain, status="succeeded",
                           authority_level=spec.required_authority.value,
                           arguments=arguments or {},
                           task_id=task_id, run_id=run_id, call_id=call_id,
                           source_mode=source_mode, evidence_refs=spec.evidence_refs,
                           result=result)
    return {"tool": name, "result": result, "evidence_refs": spec.evidence_refs}
```

### Step 3：改造 `deerflow_client.py` — 去掉工具拦截

**文件**: `backend/agent_runtime/deerflow_client.py`

```python
async def stream(self, *, run_id, task_id, skill, message, context, ...):
    # ── 新增: 注入 bridge context ──
    from backend.agent_runtime.tools import set_bridge
    set_bridge(self.tool_bridge)

    raw_stream = self.client.stream(
        message=envelope_message,
        thread_id=session_id or run_id,
        ...
    )

    async for raw_event in self._iterate_raw_stream(raw_stream):
        # ── 改造: 纯事件映射，不拦截执行 ──
        for event in mapper.map(raw_event):          # 只做 StreamEvent → dict
            # 工具执行已由 DeerFlow 内部完成，这里只做透传
            yield event
```

删除 `_map_and_execute_tools()` 方法（~75行），保留工具别名映射逻辑（移到 mapper 或独立函数）。

### Step 4：改造 `bootstrap.py` — 适配新接口

**文件**: `backend/bootstrap.py`

```python
# L234: 兼容新旧模式
workbench_tools.init_workbench_tools(tool_bridge)

# L243: DeerFlowClientAdapter.from_env 不变
deerflow=DeerFlowClientAdapter.from_env(
    tool_bridge=tool_bridge, runtime_config=runtime_config
)
```

---

## 改造影响范围

| 文件 | 改动量 | 风险 |
|------|--------|------|
| `tools.py` | `_tool()` 函数重写 + ContextVar + 删全局变量 | 中 |
| `tool_bridge.py` | `execute()` 精简，去掉重复权限判断 | 低 |
| `deerflow_client.py` | 删 `_map_and_execute_tools()` 75行，加 `set_bridge()` | 低 |
| `bootstrap.py` | 无改动或一行适配 | 极低 |

### 不改的文件

- `deerflow_config.py` — 工具注册方式不变 (`use: backend.agent_runtime.tools:tool_name`)
- `prompt_envelope.py` — 无影响
- `copilot_service.py` — 无影响
- `execution_policy.py` — 无影响
- `permission_guard.py` — 无影响

---

## 验证方案

### 1. 单元测试

```python
# tests/test_tool_deep_binding.py

def test_tool_executes_internally():
    """验证 Tool 函数内部完成完整流程，不再依赖 adapter 拦截。"""
    bridge = mock_bridge()
    set_bridge(bridge)

    # 调用工具（模拟 DeerFlow 内部执行）
    result = get_stock_context._run(symbol="AAPL")

    # 断言: bridge 的 handler 被调用了
    bridge._handlers["get_stock_context"].assert_called_once_with({"symbol": "AAPL"})
    # 断言: ledger 被写入了
    bridge._record_execution.assert_called_once()
    # 断言: 返回 JSON
    assert json.loads(result)  # 可解析

def test_blocked_tool_raises():
    """被 BLOCKED 的工具抛出异常。"""
    set_bridge(mock_bridge())
    with pytest.raises(PermissionError):
        place_real_order._run(symbol="AAPL")
```

### 2. 集成测试

```bash
# 启动后对比 tool_execution 表
# 改造前: 同一个 tool_call 产生 2 条记录
# 改造后: 同一个 tool_call 产生 1 条记录

sqlite3 data/workbench.sqlite3 \
  "SELECT tool, COUNT(*) as cnt FROM tool_execution GROUP BY tool, call_id HAVING cnt > 1"
# 改造后应返回 0 行
```

### 3. Smoke 测试

```bash
uv run python scripts/deerflow_smoke.py
# 检查 SSE 事件流中 tool_result 是否只有一个
```

---

## 注意事项

1. **stub 模式不受影响**：stub 模式走 `DeerFlowClientAdapter._stub_stream()` → `tool_bridge.execute()`，不走 DeerFlow 工具函数，改造前后行为一致。

2. **返回 JSON 字符串的影响**：改造前工具返回 Python dict → DeerFlow 自动序列化。改造后返回 JSON 字符串 → LLM 看到的是 JSON 文本。对 LLM 来说两者等价（都能理解），但前端 SSE 事件展示可能需适配（当前 `_extract_text` 已能处理 str）。

3. **tool_call 事件不再被拦截**：改造后 adapter 不再对 tool_call 事件做别名映射。如果 LLM 调用了不存在的工具名，DeerFlow 会报错，adapter 不需要补救。别名映射应移到 `DeerFlowEventMapper` 中处理展示。

4. **ContextVar 生命周期**：`set_bridge()` 在 `adapter.stream()` 入口设置，在整个生成器生命周期内有效。如果多个协程并发调用 stream()，ContextVar 自动隔离。

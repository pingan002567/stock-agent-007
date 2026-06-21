from __future__ import annotations

import asyncio
import contextvars
from concurrent.futures import CancelledError
from dataclasses import asdict, dataclass
import importlib
import os
import threading
from typing import Any, AsyncIterator, Dict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from backend.agent_runtime.deerflow_config import generate_config
from backend.agent_runtime.prompt_envelope import render_prompt_envelope
from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
from backend.app_services.permission_guard import PermissionDenied
from backend.schemas import AuthorityLevel

SYNC_STREAM_QUEUE_MAXSIZE = 64


@dataclass
class AgentRuntimeStatus:
    mode: str = "stub"
    available: bool = True
    active_client: str = "stub"
    degraded: bool = False
    degraded_reason: str | None = None
    subagent_enabled: bool = False
    plan_mode: bool = False
    client_capabilities: list[str] | None = None
    config_path: str | None = None
    model_name: str | None = None
    thinking_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeerFlowEventMapper:
    """Map DeerFlow embedded stream events into Workbench stream events.

    The mapper accepts LangGraph-like events without depending on DeerFlow
    classes. Tests feed simple objects/dicts so this boundary stays copyright
    safe and replaceable.
    """

    def __init__(self) -> None:
        self._streamed_text: set[str] = set()
        self._last_ai_text: str = ""

    def map(self, raw_event: Any) -> list[dict[str, Any]]:
        event_type, payload = self._split(raw_event)
        if event_type == "messages-tuple":
            return self._map_messages(payload)
        if event_type == "values":
            return self._map_values(payload)
        if event_type == "custom":
            return [
                {
                    "type": "reasoning",
                    "payload": {"phase": "custom", "data": self._jsonable(payload)},
                }
            ]
        if event_type == "end":
            return [{"type": "final", "payload": self._map_final(payload)}]
        return []

    def _split(self, raw_event: Any) -> tuple[str | None, Any]:
        if isinstance(raw_event, tuple) and len(raw_event) >= 2:
            return str(raw_event[0]), raw_event[1]
        if isinstance(raw_event, dict):
            event_type = (
                raw_event.get("event") or raw_event.get("type") or raw_event.get("kind")
            )
            payload = raw_event.get("data", raw_event.get("payload", raw_event))
            return str(event_type) if event_type else None, payload
        event_type = getattr(raw_event, "event", None) or getattr(
            raw_event, "type", None
        )
        payload = getattr(raw_event, "data", None) or getattr(
            raw_event, "payload", raw_event
        )
        return str(event_type) if event_type else None, payload

    def _map_messages(self, payload: Any) -> list[dict[str, Any]]:
        messages = self._messages_from_payload(payload)
        events: list[dict[str, Any]] = []
        for message in messages:
            events.extend(self._map_tool_calls(message))
            role = self._get(message, "type") or self._get(message, "role")
            content = self._get(message, "content")
            if role == "tool" or self._get(message, "tool_call_id"):
                events.append(
                    {
                        "type": "tool_result",
                        "payload": {
                            "call_id": self._get(message, "tool_call_id")
                            or self._get(message, "id"),
                            "tool": self._get(message, "name")
                            or self._get(message, "tool")
                            or "tool",
                            "result": content,
                        },
                    }
                )
            elif content:
                text = self._text(content)
                if text and text not in self._streamed_text:
                    self._streamed_text.add(text)
                    events.append({"type": "partial_answer", "payload": {"text": text}})
        return events

    def _map_tool_calls(self, message: Any) -> list[dict[str, Any]]:
        tool_calls = self._get(message, "tool_calls") or []
        events = []
        for call in tool_calls:
            # Skip placeholder/stale entries: empty name or missing id
            function = self._get(call, "function") or {}
            name = self._get(call, "name") or self._get(function, "name") or ""
            call_id = self._get(call, "id")
            if not name or not call_id:
                continue
            function = self._get(call, "function") or {}
            events.append(
                {
                    "type": "tool_call",
                    "payload": {
                        "call_id": call_id,
                        "tool": name,
                        "arguments": self._get(call, "args")
                        or self._get(call, "arguments")
                        or self._get(function, "arguments")
                        or {},
                    },
                }
            )
        return events

    def _map_values(self, payload: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        title = self._get(payload, "title")
        if title and isinstance(title, str) and title.strip():
            events.append({"type": "title", "payload": {"title": title.strip()}})
        summary: dict[str, Any] = {"phase": "values"}
        status = self._get(payload, "status")
        if status:
            summary["status"] = status
        messages = self._get(payload, "messages")
        if messages:
            latest_text = None
            for message in self._messages_from_payload(messages):
                role = self._get(message, "type") or self._get(message, "role")
                content = self._get(message, "content")
                if role == "ai" and content:
                    ai_text = self._text(content)
                    if ai_text:
                        self._last_ai_text = ai_text
                text = self._text(self._get(message, "content"))
                if text and text not in self._streamed_text:
                    latest_text = text
            if latest_text:
                summary["latest_text"] = latest_text
        events.append({"type": "reasoning", "payload": summary})
        return events

    def _map_final(self, payload: Any) -> dict[str, Any]:
        return {
            "conclusion": self._last_ai_text
            or self._get(payload, "conclusion")
            or "DeerFlow embedded stream completed.",
            "confidence": self._get(payload, "confidence") or "medium",
            "usage": self._get(payload, "usage_metadata")
            or self._get(payload, "usage")
            or {},
        }

    def _messages_from_payload(self, payload: Any) -> list[Any]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, tuple):
            return [item for item in payload if not isinstance(item, dict)]
        messages = self._get(payload, "messages")
        if isinstance(messages, list):
            return messages
        return [payload]

    def _get(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    def _text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                parts.append(
                    str(self._get(item, "text") or self._get(item, "content") or item)
                )
            return "".join(parts)
        return str(content)

    def _jsonable(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {key: self._jsonable(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._jsonable(item) for item in payload]
        if isinstance(payload, (str, int, float, bool)) or payload is None:
            return payload
        return repr(payload)


class DeerFlowClientAdapter:
    """Boundary around embedded DeerFlow.

    This stub intentionally does not copy DeerFlow internals. It preserves the
    stream contract while the project is still at local V1 architecture stage.
    Replace this class internals with `deerflow.client.DeerFlowClient` once the
    upstream source dependency is added.
    """

    def __init__(
        self,
        *,
        mode: str = "stub",
        client: Any | None = None,
        tool_bridge: WorkbenchToolBridge | None = None,
        degraded_reason: str | None = None,
        config_path: str | None = None,
        model_name: str | None = None,
        thinking_enabled: bool = True,
        subagent_enabled: bool = False,
        plan_mode: bool = False,
        client_capabilities: list[str] | None = None,
    ) -> None:
        self.mode = mode
        self.client = client
        self.tool_bridge = tool_bridge
        self.degraded_reason = degraded_reason
        self.config_path = config_path
        self.model_name = model_name or os.getenv("WORKBENCH_AI_MODEL") or "gpt-4o"
        self.thinking_enabled = thinking_enabled
        self.subagent_enabled = subagent_enabled
        self.plan_mode = plan_mode
        self.client_capabilities = client_capabilities or []
        self._active_client_override: str | None = "stub" if client is None else None

    @classmethod
    def from_env(
        cls,
        tool_bridge: WorkbenchToolBridge | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> "DeerFlowClientAdapter":
        runtime_config = runtime_config or {}
        
        # 获取 API Key，忽略占位符值
        env_api_key = os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY")
        if env_api_key and env_api_key in ("your_api_key_here", "sk-xxx", "xxx"):
            env_api_key = None
        
        _resolved_api_key = (
            env_api_key
            or runtime_config.get("api_key")
            or None
        )
        _resolved_base_url = (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("WORKBENCH_AI_BASE_URL")
            or runtime_config.get("base_url")
            or None
        )
        # If values came from persisted config, propagate to env so downstream
        # code (_try_direct, generate_config) picks them up without changes.
        if (
            _resolved_api_key
            and not os.getenv("OPENAI_API_KEY")
            and not os.getenv("WORKBENCH_AI_API_KEY")
        ):
            os.environ["WORKBENCH_AI_API_KEY"] = _resolved_api_key
        if (
            _resolved_base_url
            and not os.getenv("OPENAI_BASE_URL")
            and not os.getenv("WORKBENCH_AI_BASE_URL")
        ):
            os.environ["OPENAI_BASE_URL"] = _resolved_base_url

        ai_mode = os.getenv("WORKBENCH_AI_MODE", "").strip().lower()
        deerflow_mode = (
            os.getenv("WORKBENCH_DEERFLOW_MODE")
            or runtime_config.get("runtime_mode")
            or "embedded"
        )
        deerflow_mode = str(deerflow_mode).strip().lower() or "embedded"
        config_path = (
            os.getenv("WORKBENCH_DEERFLOW_CONFIG_PATH")
            or runtime_config.get("config_path")
            or None
        )
        model_name = (
            os.getenv("WORKBENCH_DEERFLOW_MODEL_NAME")
            or os.getenv("WORKBENCH_AI_MODEL")
            or runtime_config.get("model_name")
            or None
        )
        thinking_enabled = (
            os.getenv(
                "WORKBENCH_DEERFLOW_THINKING_ENABLED",
                str(runtime_config.get("thinking_enabled", True)),
            ).lower()
            != "false"
        )
        mode: str

        _init_errors: list[str] = []

        def _try_direct() -> "DeerFlowClientAdapter | None":
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY")
            if not api_key:
                _init_errors.append("OPENAI_API_KEY is not set in environment")
                return None
            generated_path: str | None = None
            try:
                from deerflow.client import DeerFlowClient as _DFC

                generated_path = generate_config()
                os.environ["DEER_FLOW_CONFIG_PATH"] = generated_path

                import sqlite3

                _cp_path = os.path.join(
                    os.path.dirname(generated_path),
                    "deerflow_checkpoints.sqlite3",
                )
                for _stale in (f"{_cp_path}-wal", f"{_cp_path}-shm"):
                    if os.path.isfile(_stale):
                        os.remove(_stale)
                _cp_conn = sqlite3.connect(_cp_path, check_same_thread=False)
                _cp_saver = SqliteSaver(_cp_conn)
                _cp_saver.setup()

                client = _DFC(
                    config_path=generated_path,
                    checkpointer=_cp_saver,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    subagent_enabled=False,
                    plan_mode=False,
                    available_skills={
                        "stock-researcher", "risk-officer", "strategy-analyst",
                        "rebalance-planner", "stock-monitor", "report-writer",
                    },
                )
                return cls(
                    mode="direct",
                    client=client,
                    tool_bridge=tool_bridge,
                    config_path=generated_path,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    subagent_enabled=False,
                    plan_mode=False,
                    client_capabilities=["stream", "chat", "list_models"],
                )
            except Exception as exc:
                _init_errors.append(f"direct mode init failed: {exc}")
                import logging

                logging.getLogger("deerflow_client").debug(
                    "direct mode init failed: %s", exc
                )
                return None

        def _try_embedded() -> "DeerFlowClientAdapter | None":
            try:
                module = importlib.import_module("deerflow.client")
                client_cls = getattr(module, "DeerFlowClient")
                kwargs: dict[str, Any] = {
                    "config_path": config_path,
                    "model_name": model_name,
                    "thinking_enabled": thinking_enabled,
                    "subagent_enabled": False,
                    "plan_mode": False,
                }
                client = client_cls(**kwargs)
                return cls(
                    mode="embedded",
                    client=client,
                    tool_bridge=tool_bridge,
                    config_path=config_path,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    subagent_enabled=False,
                    plan_mode=False,
                    client_capabilities=cls._detect_capabilities(client),
                )
            except Exception as exc:
                _init_errors.append(f"embedded mode init failed: {exc}")
                import logging

                logging.getLogger("deerflow_client").debug(
                    "embedded mode init failed: %s", exc
                )
                return None

        # Try modes in priority order: explicit request first, then fallback
        if ai_mode == "direct":
            result = _try_direct()
            if result is not None:
                return result
            result = _try_embedded()
            if result is not None:
                return result
            return cls(
                mode="direct",
                tool_bridge=tool_bridge,
                degraded_reason=_init_errors[-1]
                if _init_errors
                else "AI runtime init failed",
                config_path=config_path,
                model_name=model_name,
                thinking_enabled=thinking_enabled,
            )

        # Embedded mode (default): try auto-upgrade to direct when prerequisites
        # are met, then fall through to traditional embedded or stub.
        # Auto-upgrade is the key change for "AI 默认真实化" — users who
        # configure API key via the settings page get a working runtime without
        # needing WORKBENCH_AI_MODE=direct or manual config files.
        if deerflow_mode == "embedded":
            _has_api_key = bool(
                os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY")
            )
            if _has_api_key:
                result = _try_direct()
                if result is not None:
                    return result
            mode = "embedded"
            try:
                module = importlib.import_module("deerflow.client")
                client_cls = getattr(module, "DeerFlowClient")
                kwargs: dict[str, Any] = {
                    "config_path": config_path,
                    "model_name": model_name,
                    "thinking_enabled": thinking_enabled,
                    "subagent_enabled": False,
                    "plan_mode": False,
                }
                client = client_cls(**kwargs)
            except Exception as exc:
                return cls(
                    mode="embedded",
                    tool_bridge=tool_bridge,
                    degraded_reason=str(exc),
                    config_path=config_path,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                )
            return cls(
                mode="embedded",
                client=client,
                tool_bridge=tool_bridge,
                config_path=config_path,
                model_name=model_name,
                thinking_enabled=thinking_enabled,
                subagent_enabled=False,
                plan_mode=False,
                client_capabilities=cls._detect_capabilities(client),
            )

        # Default fallback: stub mode (reached when deerflow_mode != "embedded")
        return cls(
            mode="stub",
            tool_bridge=tool_bridge,
            config_path=config_path,
            model_name=model_name,
            thinking_enabled=thinking_enabled,
        )

    def status(self) -> AgentRuntimeStatus:
        # active_client reports the runtime backend: "embedded" for
        # site-packages DeerFlow, "direct" for self-generated DeerFlow,
        # "stub" for offline fallback.
        active = self._active_client_override or (
            self.mode if self.client is not None else "stub"
        )
        available = self.mode == "stub" or self.client is not None
        return AgentRuntimeStatus(
            mode=self.mode,
            available=available,
            active_client=active,
            degraded=self.degraded_reason is not None,
            degraded_reason=self.degraded_reason,
            subagent_enabled=self.subagent_enabled,
            plan_mode=self.plan_mode,
            client_capabilities=self.client_capabilities,
            config_path=self.config_path,
            model_name=self.model_name,
            thinking_enabled=self.thinking_enabled,
        )

    async def stream(
        self,
        *,
        run_id: str,
        task_id: str,
        skill: str,
        message: str,
        context: Dict[str, Any],
        skill_trace: list[dict[str, Any]] | None = None,
        history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
        subagent_enabled: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        # Both direct and embedded modes use DeerFlowClient.stream()
        if self.client is not None:
            mapper = DeerFlowEventMapper()
            tool_evidence_refs: list[str] = []
            authority_level = AuthorityLevel(
                str(context.get("_authority_level") or AuthorityLevel.A2.value)
            )
            envelope_message = render_prompt_envelope(
                user_message=message,
                skill_trace=skill_trace or [],
                context=context,
            )
            try:
                raw_stream = self.client.stream(
                    message=envelope_message,
                    thread_id=session_id or run_id,
                    model_name=self.model_name,
                    thinking_enabled=self.thinking_enabled,
                    subagent_enabled=subagent_enabled,
                    plan_mode=False,
                )
            except Exception as exc:
                self._set_degraded(str(exc), fallback_to_stub=True)
                async for event in self._stub_stream(
                    run_id=run_id,
                    task_id=task_id,
                    skill=skill,
                    message=message,
                    context=context,
                ):
                    yield event
                return

            if self.tool_bridge:
                from backend.agent_runtime.tools import set_bridge
                set_bridge(self.tool_bridge)

            stream_started = False
            try:
                async for raw_event in self._iterate_raw_stream(raw_stream):
                    stream_started = True
                    self._clear_degraded()
                    for event in mapper.map(raw_event):
                        event = self._apply_alias(event)
                        if event.get("type") == "tool_result":
                            refs = event.get("payload", {}).get("evidence_refs", [])
                            for ref in refs:
                                if ref not in tool_evidence_refs:
                                    tool_evidence_refs.append(ref)
                        elif event.get("type") == "final":
                            event.setdefault("payload", {})["tool_evidence_refs"] = list(tool_evidence_refs)
                        yield event
            except _ToolExecutionTerminalError as exc:
                self._set_degraded(exc.reason)
                for event in exc.leading_events:
                    yield event
                yield exc.error_event
                yield exc.final_event
                return
            except Exception as exc:
                if not stream_started:
                    self._set_degraded(str(exc), fallback_to_stub=True)
                    async for event in self._stub_stream(
                        run_id=run_id,
                        task_id=task_id,
                        skill=skill,
                        message=message,
                        context=context,
                    ):
                        yield event
                    return
                self._set_degraded(str(exc))
                yield self._error_event(
                    tool=None,
                    call_id=None,
                    error=str(exc),
                    authority_level=authority_level,
                    stage="embedded_stream",
                )
                yield self._final_error_payload(
                    reason=f"embedded stream failed after startup: {exc}",
                    tool_evidence_refs=tool_evidence_refs,
                )
                return
            return

        async for event in self._stub_stream(
            run_id=run_id,
            task_id=task_id,
            skill=skill,
            message=message,
            context=context,
        ):
            yield event

    async def _stub_stream(
        self,
        *,
        run_id: str,
        task_id: str,
        skill: str,
        message: str,
        context: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        reason = self.degraded_reason or "AI runtime is not configured"

        if self.tool_bridge is None or self.degraded_reason:
            yield {
                "type": "reasoning",
                "payload": {
                    "text": f"AI runtime degraded: {reason}. Cannot process request."
                },
            }
            yield {
                "type": "final",
                "payload": {
                    "conclusion": f"AI 服务不可用：{reason}。请在设置页面配置 API Key 和模型，或设置环境变量 OPENAI_API_KEY。",
                    "confidence": "low",
                    "counter_reasons": [reason, f"无法处理请求：{message}"],
                    "runtime_error": reason,
                    "hint": "Check /api/settings and /api/health for AI runtime status details",
                },
            }
            return

        try:
            tool_name, arguments, default_level = self._stub_tool_for_skill(
                skill, message, context
            )
        except Exception:
            yield {
                "type": "reasoning",
                "payload": {"text": f"Failed to resolve tool for skill: {skill}"},
            }
            yield {
                "type": "final",
                "payload": {
                    "conclusion": f"Stub runtime could not determine tool for skill: {skill}",
                    "confidence": "low",
                    "counter_reasons": [],
                    "runtime_error": f"unknown skill: {skill}",
                },
            }
            return

        authority_value = str(context.get("_authority_level") or default_level.value)
        authority_level = AuthorityLevel(authority_value)
        call_id = f"call_{tool_name}"
        tool_evidence_refs: list[str] = []

        yield {
            "type": "reasoning",
            "payload": {"text": f"Processing request using {tool_name}..."},
        }

        yield {
            "type": "tool_call",
            "payload": {
                "call_id": call_id,
                "tool": tool_name,
                "arguments": arguments,
            },
        }

        runtime_error: str | None = None
        try:
            result = self.tool_bridge.execute(
                tool_name,
                arguments,
                authority_level,
                run_id=run_id,
                task_id=task_id,
                call_id=call_id,
                source_mode="stub",
            )
            for ref in result.get("evidence_refs", []):
                if ref not in tool_evidence_refs:
                    tool_evidence_refs.append(ref)
            yield {
                "type": "tool_result",
                "payload": {"call_id": call_id, **result},
            }
        except PermissionDenied as exc:
            runtime_error = str(exc)
            yield {
                "type": "error",
                "payload": {
                    "tool": tool_name,
                    "call_id": call_id,
                    "error": runtime_error,
                    "authority_level": authority_level.value,
                },
            }
        except Exception as exc:
            runtime_error = str(exc)
            yield {
                "type": "error",
                "payload": {
                    "tool": tool_name,
                    "call_id": call_id,
                    "error": runtime_error,
                    "authority_level": authority_level.value,
                },
            }

        yield {
            "type": "partial_answer",
            "payload": {"text": f"Task analysis complete. Used tool: {tool_name}."},
        }

        final_payload: Dict[str, Any] = {
            "conclusion": f"Task completed. Used {tool_name} to process the request.",
            "confidence": "medium",
            "counter_reasons": [],
        }
        if runtime_error:
            final_payload["runtime_error"] = runtime_error
        if tool_evidence_refs:
            final_payload["tool_evidence_refs"] = tool_evidence_refs
        yield {"type": "final", "payload": final_payload}

    async def _iterate_raw_stream(self, raw_stream: Any) -> AsyncIterator[Any]:
        if hasattr(raw_stream, "__aiter__"):
            async for raw_event in raw_stream:
                yield raw_event
            return
        async for raw_event in self._bridge_sync_stream(raw_stream):
            yield raw_event

    async def _bridge_sync_stream(self, raw_stream: Any) -> AsyncIterator[Any]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(
            maxsize=SYNC_STREAM_QUEUE_MAXSIZE
        )
        done = object()
        ctx = contextvars.copy_context()

        def worker() -> None:
            try:
                for item in raw_stream:
                    self._put_sync_bridge_item(loop, queue, ("item", item))
            except Exception as exc:
                self._put_sync_bridge_item(loop, queue, ("error", exc))
            finally:
                self._put_sync_bridge_item(loop, queue, ("done", done), required=False)

        thread = threading.Thread(
            target=lambda: ctx.run(worker), name=f"deerflow-sync-stream-{uuid4().hex[:8]}", daemon=True
        )
        thread.start()
        while True:
            kind, value = await queue.get()
            if kind == "item":
                yield value
                continue
            if kind == "error":
                raise value
            break
        await asyncio.to_thread(thread.join, 0.1)

    def _put_sync_bridge_item(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[tuple[str, Any]],
        item: tuple[str, Any],
        *,
        required: bool = True,
    ) -> None:
        # Use blocking queue.put scheduled onto the event loop instead of
        # put_nowait in a callback, so bounded-queue backpressure does not turn
        # into QueueFull exceptions on the loop thread.
        try:
            asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()
        except (CancelledError, RuntimeError):
            if required:
                raise

    @staticmethod
    def _apply_alias(event: dict) -> dict:
        alias_map = {
            "strategy_backtest": "run_strategy_backtest",
            "get_strategy_list": "list_strategies",
            "get_strategy_backtest": "get_backtest_result",
        }
        if event.get("type") == "tool_call":
            tool_name = event.get("payload", {}).get("tool", "")
            if tool_name in alias_map:
                event["payload"]["tool"] = alias_map[tool_name]
        return event

    def _error_event(
        self,
        *,
        tool: str | None,
        call_id: str | None,
        error: str,
        authority_level: AuthorityLevel,
        stage: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tool": tool,
            "call_id": call_id,
            "error": error,
            "authority_level": authority_level.value,
        }
        if stage:
            payload["stage"] = stage
        return {"type": "error", "payload": payload}

    def _final_error_payload(
        self, *, reason: str, tool_evidence_refs: list[str]
    ) -> dict[str, Any]:
        payload = {
            "type": "final",
            "payload": {
                "conclusion": "本次 embedded 运行提前结束。",
                "confidence": "low",
                "counter_reasons": [reason],
                "runtime_error": reason,
            },
        }
        if tool_evidence_refs:
            payload["payload"]["tool_evidence_refs"] = list(tool_evidence_refs)
        return payload

    def _set_degraded(self, reason: str, *, fallback_to_stub: bool = False) -> None:
        self.degraded_reason = reason
        if fallback_to_stub:
            self._active_client_override = "stub"

    def _clear_degraded(self) -> None:
        self.degraded_reason = None
        if self.client is not None:
            self._active_client_override = None

    @staticmethod
    def _detect_capabilities(client: Any) -> list[str]:
        capabilities = []
        for name in ["stream", "chat", "list_models", "list_skills"]:
            if callable(getattr(client, name, None)):
                capabilities.append(name)
        return capabilities

    def _stub_tool_for_skill(
        self, skill: str, message: str, context: Dict[str, Any]
    ) -> tuple[str, dict[str, Any], AuthorityLevel]:
        symbol = self._message_symbol(message, context)
        lower = message.lower()
        if skill == "strategy-analyst":
            return (
                "run_strategy_backtest",
                {
                    "strategy_id": "concentration-control",
                    "universe": [symbol],
                    "period": {"days": 30},
                },
                AuthorityLevel.A3,
            )
        if skill == "rebalance-planner":
            if (
                ("确认" in message and "草案" in message and "审查" not in message)
                or any(word in message for word in ["approve", "批准"])
            ):
                if self.tool_bridge:
                    drafts = self.tool_bridge.rebalance_draft_service.list(
                        symbol=symbol.upper(),
                        status="pending_user_confirmation",
                        limit=1,
                    )
                    if drafts:
                        return "confirm_rebalance_draft", {"draft_id": drafts[0].draft_id}, AuthorityLevel.A4
                return "confirm_rebalance_draft", {}, AuthorityLevel.A4
            if (
                ("驳回" in message and ("草案" in message or "全部" in message))
                or any(word in message for word in ["reject", "decline"])
            ):
                if self.tool_bridge:
                    drafts = self.tool_bridge.rebalance_draft_service.list(
                        symbol=symbol.upper(),
                        status="pending_user_confirmation",
                        limit=1,
                    )
                    if drafts:
                        return "reject_rebalance_draft", {"draft_id": drafts[0].draft_id}, AuthorityLevel.A4
                return "reject_rebalance_draft", {}, AuthorityLevel.A4
            if (
                any(word in message for word in ["交易前审查", "执行前审查"])
                or (
                    "审查" in message
                    and any(word in message for word in ["拟单", "草案", "执行"])
                )
                or "适合执行" in message
                or (
                    "review" in lower
                    and any(
                        word in lower for word in ["draft", "pre-trade", "execution"]
                    )
                )
            ):
                draft_id = (
                    self.tool_bridge.resolve_confirmed_draft_id(symbol)
                    if self.tool_bridge
                    else None
                )
                arguments = {"draft_id": draft_id} if draft_id else {}
                return "create_pre_trade_review", arguments, AuthorityLevel.A4
            return (
                "generate_draft_order",
                {"symbol": symbol, "target_weight_pct": 15},
                AuthorityLevel.A4,
            )
        if skill == "risk-officer":
            if self._wants_review_inbox(message):
                if "高优先级" in message:
                    return (
                        "list_review_inbox",
                        {"priority": "high", "limit": 10},
                        AuthorityLevel.A3,
                    )
                if "为什么重要" in message:
                    return "list_review_inbox", {"limit": 1}, AuthorityLevel.A3
                return "summarize_review_inbox", {}, AuthorityLevel.A3
            if self._wants_decision_journal_review(message):
                explicit_symbol = (
                    self._explicit_message_symbol(message)
                    or self._context_symbol(context)
                    or None
                )
                if "最好" in message or "表现" in message:
                    return (
                        "summarize_decision_outcomes",
                        {"symbol": explicit_symbol},
                        AuthorityLevel.A3,
                    )
                journal_symbol = (
                    None
                    if any(word in message for word in ["最近一次", "最新"])
                    else explicit_symbol
                )
                return (
                    "list_decision_journal",
                    {"symbol": journal_symbol, "limit": 1},
                    AuthorityLevel.A3,
                )
            if (
                (
                    "paper" in lower
                    and any(
                        word in message for word in ["复盘", "调仓效果", "绩效归因"]
                    )
                )
                or "paper portfolio" in lower
                or (
                    "sandbox" in lower
                    and any(word in message for word in ["复盘", "绩效"])
                )
            ):
                return "analyze_paper_performance", {}, AuthorityLevel.A3
            return "evaluate_policy_risk", {}, AuthorityLevel.A3
        if skill == "stock-monitor":
            return "get_monitor_events", {"limit": 5}, AuthorityLevel.A2
        if skill == "report-writer":
            return (
                "generate_report",
                self._stub_report_arguments(message, context),
                AuthorityLevel.A2,
            )
        return "get_stock_context", {"symbol": symbol}, AuthorityLevel.A2

    def _wants_decision_journal_review(self, message: str) -> bool:
        lower = message.lower()
        return (
            "决策档案" in message
            or "建议链路" in message
            or (
                "ai" in lower
                and any(word in message for word in ["调仓建议", "复盘", "建议链路"])
            )
            or (
                "paper" in lower
                and any(
                    word in message for word in ["调仓建议", "表现最好", "建议链路"]
                )
            )
        )

    def _wants_review_inbox(self, message: str) -> bool:
        return (
            "今天我需要处理什么" in message
            or "列出高优先级待办" in message
            or "解释这条待办为什么重要" in message
            or ("待办" in message and any(word in message for word in ["高优先级", "今天", "为什么重要"]))
            or any(phrase in message for phrase in ["标记已处理", "处理待办", "处理收件箱", "清理收件箱"])
            or ("处理" in message and "收件箱" in message)
            or ("处理" in message and "待办" in message)
        )

    def _message_symbol(self, message: str, context: Dict[str, Any]) -> str:
        context_symbol = self._context_symbol(context)
        if context_symbol:
            return context_symbol
        explicit = self._explicit_message_symbol(message)
        if explicit:
            return explicit
        return "AAPL"

    def _context_symbol(self, context: Dict[str, Any]) -> str | None:
        symbol = str(context.get("symbol") or "").upper()
        if symbol:
            return symbol
        summary = context.get("symbol_summary")
        if isinstance(summary, dict):
            summary_symbol = str(summary.get("symbol") or "").upper()
            if summary_symbol:
                return summary_symbol
        return None

    def _explicit_message_symbol(self, message: str) -> str | None:
        for token in message.replace("，", " ").replace(",", " ").split():
            cleaned = token.strip(" .:;!?()[]{}'\"")
            if cleaned in {"AI", "A3", "A4", "A5"}:
                continue
            if (
                1 <= len(cleaned) <= 8
                and cleaned.isascii()
                and cleaned.upper() == cleaned
                and any(ch.isalpha() for ch in cleaned)
            ):
                return cleaned
        return None

    def _stub_report_arguments(
        self, message: str, context: Dict[str, Any]
    ) -> dict[str, Any]:
        lower = message.lower()
        if (
            any(word in message for word in ["盯盘", "异动", "提醒"])
            or "monitor" in lower
        ):
            return {
                "report_type": "monitor_review",
                "source_type": "monitor_event",
                "source_id": "latest",
            }
        if any(word in message for word in ["回测", "策略"]) or any(
            word in lower for word in ["backtest", "strategy"]
        ):
            return {
                "report_type": "strategy_backtest",
                "source_type": "backtest_run",
                "source_id": "latest",
            }
        return {
            "report_type": "stock_research",
            "source_type": "stock",
            "source_id": self._context_symbol(context) or "AAPL",
        }


class _ToolExecutionTerminalError(Exception):
    def __init__(
        self,
        *,
        reason: str,
        leading_events: list[dict[str, Any]],
        error_event: dict[str, Any],
        final_event: dict[str, Any],
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.leading_events = leading_events
        self.error_event = error_event
        self.final_event = final_event

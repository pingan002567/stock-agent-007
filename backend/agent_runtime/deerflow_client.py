from __future__ import annotations

import asyncio
import contextvars
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import importlib
import os
import threading
from typing import Any, AsyncIterator, Dict, Iterator
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from backend.agent_runtime import skill_specs
from backend.agent_runtime.deerflow_config import generate_config
from backend.agent_runtime.prompt_envelope import is_usable_session_title, render_prompt_envelope
from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
from backend.app_services.permission_guard import PermissionDenied
from backend.schemas import AuthorityLevel


def _lead_available_skills() -> set[str] | None:
    """Skills projection for DeerFlowClient.

    LocalSandbox + host bash cannot enforce per-Agent skill FS isolation. Passing a
    restricted ``available_skills`` set then raises SandboxRuntimeError on every
    turn. Use the shared unrestricted skill view when host bash is on.
    """
    from backend.agent_runtime.deerflow_config import _host_bash_explicitly_allowed, _sandbox_mode

    if _sandbox_mode() == "host" and _host_bash_explicitly_allowed():
        return None
    return skill_specs.subagent_names()

def _turn_upload_files(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in attachments or []:
        filename = str(item.get("filename") or "")
        if not filename or filename in seen:
            continue
        seen.add(filename)
        files.append({"filename": filename, "size": int(item.get("size") or 0)})
    return files


@contextmanager
def _with_human_message_kwargs(extra_kwargs: dict[str, Any]) -> Iterator[None]:
    """Merge additional_kwargs onto DeerFlowClient-built HumanMessage.

    Embedded ``DeerFlowClient.stream`` constructs ``HumanMessage(content=...)``
    without workbench metadata. Same seam as turn uploads: inject
    ``files`` / ``human_input_response`` so UploadsMiddleware and (upstream)
    clarification resume can see them.
    """
    if not extra_kwargs:
        yield
        return
    from langchain_core.messages import HumanMessage

    original = HumanMessage.__init__

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> None:
        extra = dict(kwargs.get("additional_kwargs") or {})
        for key, value in extra_kwargs.items():
            if key not in extra:
                extra[key] = value
        kwargs["additional_kwargs"] = extra
        original(self, *args, **kwargs)

    HumanMessage.__init__ = wrapped  # type: ignore[method-assign]
    try:
        yield
    finally:
        HumanMessage.__init__ = original  # type: ignore[method-assign]


@contextmanager
def _with_turn_upload_files(files: list[dict[str, Any]]) -> Iterator[None]:
    """Backward-compatible alias for upload-only injection."""
    with _with_human_message_kwargs({"files": files} if files else {}):
        yield


SYNC_STREAM_QUEUE_MAXSIZE = 64

# LangGraph super-step ceiling per turn. Single-agent turns rarely exceed the
# default 100; subagent-enabled turns delegate to nested graphs and need more.
# Both overridable via env for ops without a code change.
_DEFAULT_RECURSION_LIMIT = 100
# Nested task()/skill graphs burn LangGraph super-steps quickly on multi-section
# reports. sector-rotation-report keeps tool budgets low; 320 is the safety ceiling.
_SUBAGENT_RECURSION_LIMIT = 320


def _recursion_limit(subagent_enabled: bool) -> int:
    env_key = "WORKBENCH_AI_RECURSION_LIMIT_SUBAGENT" if subagent_enabled else "WORKBENCH_AI_RECURSION_LIMIT"
    default = _SUBAGENT_RECURSION_LIMIT if subagent_enabled else _DEFAULT_RECURSION_LIMIT
    raw = (os.getenv(env_key) or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return default


def _wire_native_tool_groups(client: Any) -> None:
    """Honor DeerFlow ``AgentConfig.tool_groups`` on the embedded client path.

    ``make_lead_agent`` already passes ``groups=agent_config.tool_groups`` into
    ``get_available_tools``. ``DeerFlowClient._get_tools`` currently ignores that
    field — bridge the same native API at the adapter boundary (no custom allowlist).
    """

    def _get_tools(*, model_name: str | None = None, subagent_enabled: bool = False):
        from deerflow.config.agents_config import load_agent_config
        from deerflow.tools import get_available_tools

        groups = None
        agent_name = getattr(client, "_agent_name", None)
        if agent_name:
            try:
                agent_cfg = load_agent_config(agent_name)
            except FileNotFoundError:
                agent_cfg = None
            if agent_cfg is not None:
                groups = agent_cfg.tool_groups
        return get_available_tools(
            model_name=model_name,
            groups=groups,
            subagent_enabled=subagent_enabled,
        )

    client._get_tools = _get_tools  # instance shadow of the class staticmethod


def _client_kwargs_from(adapter: "DeerFlowClientAdapter", base: Any, *, agent_name: str) -> dict[str, Any]:
    """Build DeerFlowClient kwargs for a sibling client sharing checkpointer/config."""
    return {
        "config_path": adapter.config_path,
        "checkpointer": getattr(base, "_checkpointer", None),
        "model_name": getattr(base, "_model_name", None) or adapter.model_name,
        "thinking_enabled": getattr(base, "_thinking_enabled", adapter.thinking_enabled),
        "subagent_enabled": getattr(base, "_subagent_enabled", adapter.subagent_enabled),
        "plan_mode": getattr(base, "_plan_mode", adapter.plan_mode),
        "agent_name": agent_name,
        "available_skills": getattr(base, "_available_skills", None),
    }


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

    def __init__(self, historical_msg_ids: set[str] | None = None) -> None:
        self._streamed_text: set[str] = set()
        self._emitted_tool_calls: set[str] = set()
        # DeerFlow message ids already in the thread before this run (from the
        # checkpoint). On a resumed (session-keyed) thread the first "values" snapshot
        # replays those messages, so DeerFlowClient.stream re-emits their
        # text/tool_calls/tool_results (every event carries the message "id"). Skip any
        # replayed message by id — covers historical answer text AND tool cards.
        self._historical_msg_ids: set[str] = set(historical_msg_ids or ())
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
            msg_id = self._get(message, "id")
            # Skip whole messages replayed from a prior run of a resumed thread.
            if msg_id and msg_id in self._historical_msg_ids:
                continue
            events.extend(self._map_tool_calls(message))
            role = self._get(message, "type") or self._get(message, "role")
            content = self._get(message, "content")
            if role == "tool" or self._get(message, "tool_call_id"):
                result_call_id = self._get(message, "tool_call_id") or self._get(message, "id")
                tool_payload: dict[str, Any] = {
                    "call_id": result_call_id,
                    "tool": self._get(message, "name")
                    or self._get(message, "tool")
                    or "tool",
                    "result": content,
                }
                # DeerFlow ≥ human_input: ToolMessage.artifact.human_input
                artifact = self._get(message, "artifact")
                if artifact is not None:
                    tool_payload["artifact"] = artifact
                events.append({"type": "tool_result", "payload": tool_payload})
            elif role in ("ai", "assistant") and content:
                # Only assistant content is the answer. Human (the prompt envelope) /
                # system messages must never be echoed into the bubble.
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
            # Dedupe within a stream: the same tool_call can appear in multiple
            # snapshots; emit each call_id at most once. (Cross-run replay is already
            # filtered upstream by message id in _map_messages.)
            if call_id in self._emitted_tool_calls:
                continue
            self._emitted_tool_calls.add(call_id)
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
        # DeerFlow 用线程首条 HumanMessage 生成标题；首条是 prompt envelope
        # （JSON 或 <workbench_context>），必须拦下，否则会话标题泄漏内部上下文。
        if is_usable_session_title(title if isinstance(title, str) else None):
            events.append({"type": "title", "payload": {"title": str(title).strip()}})
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
                # Only assistant content is reasoning/answer text. Skip human (the
                # prompt envelope), system, and tool messages — tool results show as
                # tool cards; the input envelope must never surface in the bubble.
                if role not in ("ai", "assistant") or not content:
                    continue
                ai_text = self._text(content)
                if ai_text:
                    self._last_ai_text = ai_text
                    if ai_text not in self._streamed_text:
                        latest_text = ai_text
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
        # Per-authority DeerFlowClient instances (same checkpointer). Avoids races
        # when concurrent streams need different AgentConfig.tool_groups.
        self._clients_by_agent: dict[str, Any] = {}
        if client is not None:
            _wire_native_tool_groups(client)
            name = getattr(client, "_agent_name", None)
            if name:
                self._clients_by_agent[name] = client

    def _client_for_authority(self, authority_level: str | None) -> Any:
        """Pick/create the DeerFlowClient whose AgentConfig.tool_groups match authority."""
        from backend.agent_runtime.deerflow_config import (
            agent_name_for_authority,
            ensure_authority_agents,
        )

        if self.client is None:
            return None
        ensure_authority_agents()
        agent_name = agent_name_for_authority(authority_level)
        cached = self._clients_by_agent.get(agent_name)
        if cached is not None:
            return cached

        # Reuse the primary client if it has no agent_name yet.
        primary_name = getattr(self.client, "_agent_name", None)
        if not primary_name and agent_name not in self._clients_by_agent:
            self.client._agent_name = agent_name
            _wire_native_tool_groups(self.client)
            # Force rebuild on next stream so groups take effect.
            self.client._agent = None
            self.client._agent_config_key = None
            self._clients_by_agent[agent_name] = self.client
            return self.client

        client_cls = type(self.client)
        sibling = client_cls(**_client_kwargs_from(self, self.client, agent_name=agent_name))
        _wire_native_tool_groups(sibling)
        self._clients_by_agent[agent_name] = sibling
        return sibling

    @classmethod
    def from_env(
        cls,
        tool_bridge: WorkbenchToolBridge | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> "DeerFlowClientAdapter":
        runtime_config = runtime_config or {}
        
        # 获取 API Key，忽略占位符值。注意：_try_direct / generate_config 会直接
        # 再读一次 os.getenv("OPENAI_API_KEY")，所以仅把局部变量置空不够——必须把
        # 占位符从 os.environ 里清掉，否则像 .env 里残留的 your_api_key_here 会盖过
        # 页面保存的有效 key，导致真实 LLM 调用 401。
        _PLACEHOLDER_KEYS = {"your_api_key_here", "sk-xxx", "xxx", ""}
        for _k in ("OPENAI_API_KEY", "WORKBENCH_AI_API_KEY"):
            if (os.getenv(_k) or "").strip() in _PLACEHOLDER_KEYS:
                os.environ.pop(_k, None)
        env_api_key = os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY")
        
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

        # Runtime-level flags: Lead Agent decides per-turn delegation. Env can
        # still force the whole client off for ops.
        subagent_supported = skill_specs.subagent_supported()
        plan_mode_supported = skill_specs.plan_mode_supported()

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
                    subagent_enabled=subagent_supported,
                    plan_mode=plan_mode_supported,
                    available_skills=_lead_available_skills(),
                )
                return cls(
                    mode="direct",
                    client=client,
                    tool_bridge=tool_bridge,
                    config_path=generated_path,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    subagent_enabled=subagent_supported,
                    plan_mode=plan_mode_supported,
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
                    "subagent_enabled": subagent_supported,
                    "plan_mode": plan_mode_supported,
                }
                client = client_cls(**kwargs)
                return cls(
                    mode="embedded",
                    client=client,
                    tool_bridge=tool_bridge,
                    config_path=config_path,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    subagent_enabled=subagent_supported,
                    plan_mode=plan_mode_supported,
                    client_capabilities=cls._detect_capabilities(client),
                )
            except Exception as exc:
                _init_errors.append(f"embedded mode init failed: {exc}")
                import logging

                logging.getLogger("deerflow_client").debug(
                    "embedded mode init failed: %s", exc
                )
                return None

        # Explicit stub request short-circuits all real-runtime attempts, so a
        # deterministic stub can be forced regardless of installed harness or
        # ambient OPENAI_* credentials (used by the test suite).
        if ai_mode == "stub":
            return cls(
                mode="stub",
                tool_bridge=tool_bridge,
                config_path=config_path,
                model_name=model_name,
                thinking_enabled=thinking_enabled,
                subagent_enabled=subagent_supported,
                plan_mode=plan_mode_supported,
            )

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
                subagent_enabled=subagent_supported,
                plan_mode=plan_mode_supported,
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
                    "subagent_enabled": subagent_supported,
                    "plan_mode": plan_mode_supported,
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
                    subagent_enabled=subagent_supported,
                    plan_mode=plan_mode_supported,
                )
            return cls(
                mode="embedded",
                client=client,
                tool_bridge=tool_bridge,
                config_path=config_path,
                model_name=model_name,
                thinking_enabled=thinking_enabled,
                subagent_enabled=subagent_supported,
                plan_mode=plan_mode_supported,
                client_capabilities=cls._detect_capabilities(client),
            )

        # Default fallback: stub mode (reached when deerflow_mode != "embedded")
        return cls(
            mode="stub",
            tool_bridge=tool_bridge,
            config_path=config_path,
            model_name=model_name,
            thinking_enabled=thinking_enabled,
            subagent_enabled=subagent_supported,
            plan_mode=plan_mode_supported,
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

    # ── memory management (public DeerFlow client API passthrough) ──
    # 记忆写入侧由 deerflow_config 的 memory 段开启；这里补读取/纠偏侧，
    # 供设置页「AI 记忆」区块查看/编辑/清空用户事实库。stub 模式下降级为
    # supported=False，前端据此隐藏区块。

    def _memory_call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        fn = getattr(self.client, method, None) if self.client is not None else None
        if not callable(fn):
            return {"supported": False, "error": f"{method} unavailable in {self.mode} mode"}
        try:
            result = fn(*args, **kwargs)
            return {"supported": True, **(result if isinstance(result, dict) else {"result": result})}
        except Exception as exc:
            return {"supported": True, "error": str(exc)}

    def memory_status(self) -> dict[str, Any]:
        return self._memory_call("get_memory_status")

    def clear_memory(self) -> dict[str, Any]:
        return self._memory_call("clear_memory")

    def create_memory_fact(
        self, content: str, category: str = "context", confidence: float = 0.5
    ) -> dict[str, Any]:
        return self._memory_call(
            "create_memory_fact", content=content, category=category, confidence=confidence
        )

    def update_memory_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        return self._memory_call(
            "update_memory_fact",
            fact_id=fact_id,
            content=content,
            category=category,
            confidence=confidence,
        )

    def delete_memory_fact(self, fact_id: str) -> dict[str, Any]:
        return self._memory_call("delete_memory_fact", fact_id)

    # ── MCP servers（无代码接入外部数据源/工具） ──

    def mcp_config(self) -> dict[str, Any]:
        """Read MCP server configs from extensions_config.json (via harness)."""
        return self._memory_call("get_mcp_config")

    def update_mcp_config(self, mcp_servers: dict[str, Any]) -> dict[str, Any]:
        """Overwrite MCP server configs. Harness 侧做原子写入、agent 失效重建、
        缓存重载；MCP 工具缓存按配置文件 mtime 自动失效，下一轮对话即生效。"""
        return self._memory_call("update_mcp_config", mcp_servers)

    # ── file uploads (RAG：研报/年报 PDF 等直接给 AI 读) ──

    def upload_files(self, thread_id: str, files: list[str]) -> dict[str, Any]:
        """Upload local files into a session thread's uploads directory.

        DeerFlow converts PDF/Word/Excel/PPT to Markdown on upload; on the next
        turn UploadsMiddleware injects the file list (with outline) into the
        prompt and the agent reads content via the read-only sandbox file tools
        (ls/glob/grep/read_file) registered in deerflow_config.
        """
        # 复用 _memory_call 的护栏语义：stub/降级模式返回 supported=False
        return self._memory_call("upload_files", thread_id, files)

    def list_uploads(self, thread_id: str) -> dict[str, Any]:
        """List files in a session thread's uploads directory."""
        return self._memory_call("list_uploads", thread_id)

    def delete_upload(self, thread_id: str, filename: str) -> dict[str, Any]:
        """Delete one uploaded file (and companion .md for convertible types)."""
        return self._memory_call("delete_upload", thread_id, filename)

    def _existing_thread_msg_ids(self, thread_id: str | None) -> set[str]:
        """DeerFlow message ids already in the thread's checkpoint (prior runs).

        Read from DeerFlow's own persisted checkpoint via ``get_thread`` — the same
        source the resumed-thread replay comes from, so the ids match exactly and the
        filter survives a backend restart (unlike in-memory tracking).
        """
        if not thread_id or self.client is None:
            return set()
        get_thread = getattr(self.client, "get_thread", None)
        if not callable(get_thread):
            return set()
        try:
            checkpoints = (get_thread(thread_id) or {}).get("checkpoints") or []
            messages = (checkpoints[-1].get("values") or {}).get("messages") or [] if checkpoints else []
        except Exception:
            return set()
        ids: set[str] = set()
        for m in messages:
            mid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
            if mid:
                ids.add(str(mid))
        return ids

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
        subagent_enabled: bool = True,
        plan_mode: bool = True,
        budget: Dict[str, Any] | None = None,
        model_name: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        human_input_response: dict[str, Any] | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        effective_model = model_name or self.model_name
        # Both direct and embedded modes use DeerFlowClient.stream()
        if self.client is not None:
            # On a resumed session thread, DeerFlow re-streams prior-run messages from
            # the first values snapshot. Filter that replay out of the live stream using
            # the ids ALREADY in the thread's checkpoint — same source as the replay, so
            # ids always match, and persisted so it survives a backend restart.
            historical_msg_ids = self._existing_thread_msg_ids(session_id or run_id)
            mapper = DeerFlowEventMapper(historical_msg_ids=historical_msg_ids)
            tool_evidence_refs: list[str] = []
            authority_level = AuthorityLevel(
                str(context.get("_authority_level") or AuthorityLevel.A2.value)
            )
            envelope_message = render_prompt_envelope(
                user_message=message,
                context=context,
            )
            try:
                active_client = self._client_for_authority(
                    str(context.get("_authority_level") or "")
                ) or self.client
                raw_stream = active_client.stream(
                    message=envelope_message,
                    # Per-session thread: the DeerFlow checkpointer keeps full
                    # multi-turn state across runs of the same conversation. NOTE: on
                    # a resumed thread the first "values" snapshot contains prior runs'
                    # messages, and DeerFlowClient.stream re-emits their tool_calls /
                    # tool_results (their msg ids aren't in this call's streamed_ids).
                    # Filtering that replay is handled at the mapper boundary.
                    thread_id=session_id or run_id,
                    model_name=effective_model,
                    thinking_enabled=self.thinking_enabled,
                    subagent_enabled=subagent_enabled,
                    # plan_mode（TodoMiddleware）：write_todos 计划清单进流 +
                    # 未完成 todo 阻止提前收口。默认开，可用 WORKBENCH_AI_PLAN_MODE=off 关掉。
                    plan_mode=plan_mode,
                    # Subagent turns fan out to nested graphs; extra LangGraph
                    # super-steps avoid GRAPH_RECURSION_LIMIT on legitimate plans.
                    recursion_limit=_recursion_limit(subagent_enabled),
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
                from backend.agent_runtime.tools import set_bridge, set_run_context
                set_bridge(self.tool_bridge)
                # Attribute real-mode tool executions to this run + enforce the
                # request authority (the agent invokes StructuredTools, not the
                # bridge.execute path that carries this context in stub mode).
                set_run_context(
                    run_id=run_id,
                    task_id=task_id,
                    source_mode=self.mode,
                    authority_level=str(context.get("_authority_level") or ""),
                )

            stream_started = False
            turn_files = _turn_upload_files(attachments)
            human_kwargs: dict[str, Any] = {}
            if turn_files:
                human_kwargs["files"] = turn_files
            if human_input_response:
                human_kwargs["human_input_response"] = human_input_response
            try:
                with _with_human_message_kwargs(human_kwargs):
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
                    "conclusion": f"AI 服务不可用：{reason}。请在设置页「模型接入」连接提供商并选择默认模型。",
                    "confidence": "low",
                    "counter_reasons": [reason, f"无法处理请求：{message}"],
                    "runtime_error": reason,
                    "hint": "Check /api/settings and /api/health for AI runtime status details",
                },
            }
            return

        try:
            resolved_skill = self._stub_skill_from_message(skill, message, context)
            tool_name, arguments, default_level = self._stub_tool_for_skill(
                resolved_skill, message, context
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

    def _stub_skill_from_message(
        self, skill: str, message: str, context: Dict[str, Any]
    ) -> str:
        """Stub-only heuristic: pick a domain tool family from the user text.

        Production routing is DeerFlow Lead Agent. Tests still need a deterministic
        tool so the workbench contract can be exercised without a model.
        """
        if skill and skill not in {"lead-agent", "copilot", "copilot_chat", ""}:
            return skill
        page = str(context.get("page") or "")
        lower = message.lower()

        def has(*words: str) -> bool:
            return any(word in message for word in words)

        if message.startswith("[定时任务·") or "你是值班研究员" in message:
            return "risk-officer"
        if self._wants_review_inbox(message) or self._wants_decision_journal_review(message):
            return "risk-officer"
        if (
            ("paper" in lower and has("复盘", "调仓效果", "绩效归因"))
            or "paper portfolio" in lower
            or ("sandbox" in lower and has("复盘", "绩效"))
        ):
            return "risk-officer"
        if (
            has("轮动", "板块深挖", "催化剂日历", "行业轮动", "板块轮动")
            or ("组合报告" in message and has("板块", "轮动", "催化剂"))
            or "轮动概览" in message
        ):
            return "sector-rotation-report"
        if has("报告", "复盘", "总结", "简报", "盘前") or "report" in lower:
            return "report-writer"
        if has("回测", "策略") or any(word in lower for word in ("backtest", "strategy")):
            return "strategy-analyst"
        if has("调仓", "拟单", "仓位"):
            return "rebalance-planner"
        if has("风险", "风控", "集中度"):
            return "risk-officer"
        if has("盯盘", "异动", "提醒"):
            return "stock-monitor"
        if has("研究", "深研", "分析") or "research" in lower:
            return "stock-researcher"
        if page == "holdings":
            return "risk-officer"
        return "stock-researcher"

    def _stub_tool_for_skill(
        self, skill: str, message: str, context: Dict[str, Any]
    ) -> tuple[str, dict[str, Any], AuthorityLevel]:
        if message.startswith("[定时任务·") or "你是值班研究员" in message:
            return "get_portfolio_snapshot", {}, AuthorityLevel.A3
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

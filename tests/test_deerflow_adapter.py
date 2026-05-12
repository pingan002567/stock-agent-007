from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from backend.agent_runtime.deerflow_client import (
    SYNC_STREAM_QUEUE_MAXSIZE,
    DeerFlowClientAdapter,
    DeerFlowEventMapper,
)


def collect_mapped(raw_events):
    mapper = DeerFlowEventMapper()
    return [event for raw in raw_events for event in mapper.map(raw)]


def test_event_mapper_maps_ai_message_tuple_to_partial_answer():
    events = collect_mapped(
        [
            (
                "messages-tuple",
                [SimpleNamespace(type="ai", content="正在分析 AAPL 风险")],
            )
        ]
    )

    assert [event["type"] for event in events] == ["partial_answer"]
    assert events[0]["payload"]["text"] == "正在分析 AAPL 风险"


@dataclass
class StreamEvent:
    type: str
    data: object


def test_event_mapper_maps_stream_event_object():
    events = collect_mapped([StreamEvent(type="custom", data={"phase": "trace", "note": "ok"})])

    assert events == [{"type": "reasoning", "payload": {"phase": "custom", "data": {"phase": "trace", "note": "ok"}}}]


def test_event_mapper_maps_tool_calls_to_tool_call():
    events = collect_mapped(
        [
            (
                "messages-tuple",
                [
                    SimpleNamespace(
                        type="ai",
                        content="",
                        tool_calls=[{"id": "call_1", "name": "get_quote", "args": {"symbol": "AAPL"}}],
                    )
                ],
            )
        ]
    )

    assert [event["type"] for event in events] == ["tool_call"]
    assert events[0]["payload"] == {
        "call_id": "call_1",
        "tool": "get_quote",
        "arguments": {"symbol": "AAPL"},
    }


def test_event_mapper_maps_openai_style_function_tool_call_arguments():
    events = collect_mapped(
        [
            (
                "messages-tuple",
                [
                    SimpleNamespace(
                        type="ai",
                        content="",
                        tool_calls=[
                            {
                                "id": "call_2",
                                "function": {"name": "get_stock_context", "arguments": {"symbol": "AAPL"}},
                            }
                        ],
                    )
                ],
            )
        ]
    )

    assert [event["type"] for event in events] == ["tool_call"]
    assert events[0]["payload"] == {
        "call_id": "call_2",
        "tool": "get_stock_context",
        "arguments": {"symbol": "AAPL"},
    }


def test_event_mapper_maps_tool_message_to_tool_result():
    events = collect_mapped(
        [
            (
                "messages-tuple",
                [SimpleNamespace(type="tool", name="get_quote", tool_call_id="call_1", content='{"last": 193.7}')],
            )
        ]
    )

    assert [event["type"] for event in events] == ["tool_result"]
    assert events[0]["payload"] == {
        "call_id": "call_1",
        "tool": "get_quote",
        "result": '{"last": 193.7}',
    }


def test_event_mapper_maps_end_usage_to_final():
    events = collect_mapped([("end", {"usage_metadata": {"input_tokens": 8, "output_tokens": 13}})])

    assert [event["type"] for event in events] == ["final"]
    assert events[0]["payload"]["usage"] == {"input_tokens": 8, "output_tokens": 13}


def test_event_mapper_does_not_repeat_text_from_values_after_partial_answer():
    events = collect_mapped(
        [
            ("messages-tuple", [SimpleNamespace(type="ai", content="同一段文本")]),
            ("values", {"messages": [SimpleNamespace(type="ai", content="同一段文本")], "status": "running"}),
        ]
    )

    partials = [event for event in events if event["type"] == "partial_answer"]
    assert len(partials) == 1
    assert partials[0]["payload"]["text"] == "同一段文本"
    assert any(event["type"] == "reasoning" for event in events)


def test_adapter_falls_back_to_stub_when_embedded_import_fails(monkeypatch):
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_client.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("No module named 'deerflow'")),
    )

    adapter = DeerFlowClientAdapter.from_env()

    assert adapter.status().to_dict()["active_client"] == "stub"
    assert adapter.status().to_dict()["degraded"] is True
    assert "No module named" in adapter.status().to_dict()["degraded_reason"]
    assert adapter.status().to_dict()["client_capabilities"] == []


def test_adapter_embedded_mode_maps_fake_client_stream(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def chat(self):
            return None

        def list_models(self):
            return []

        def list_skills(self):
            return []

        async def stream(self, **kwargs):
            yield ("messages-tuple", [SimpleNamespace(type="ai", content="fake delta")])
            yield (
                "messages-tuple",
                [SimpleNamespace(type="tool", name="get_quote", tool_call_id="call_1", content="ok")],
            )
            yield ("end", {"usage_metadata": {"total_tokens": 3}})

    deerflow_pkg = ModuleType("deerflow")
    client_mod = ModuleType("deerflow.client")
    client_mod.DeerFlowClient = FakeClient
    monkeypatch.setitem(sys.modules, "deerflow", deerflow_pkg)
    monkeypatch.setitem(sys.modules, "deerflow.client", client_mod)
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_CONFIG_PATH", "/tmp/deerflow.toml")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODEL_NAME", "demo-model")

    adapter = DeerFlowClientAdapter.from_env()

    async def collect():
        return [
            event
            async for event in adapter.stream(
                run_id="run_1",
                task_id="task_1",
                skill="risk-officer",
                message="分析 AAPL",
                context={},
            )
        ]

    events = asyncio.run(collect())
    status = adapter.status().to_dict()
    assert status["active_client"] == "embedded"
    assert status["config_path"] == "/tmp/deerflow.toml"
    assert status["model_name"] == "demo-model"
    assert status["thinking_enabled"] is True
    assert status["client_capabilities"] == ["stream", "chat", "list_models", "list_skills"]
    assert [event["type"] for event in events] == ["partial_answer", "tool_result", "final"]
    assert events[0]["payload"]["text"] == "fake delta"
    assert events[-1]["payload"]["usage"] == {"total_tokens": 3}


def test_adapter_sync_stream_is_bridged_without_blocking_event_loop():
    class FakeClient:
        def stream(self, **kwargs):
            def raw_stream():
                yield ("messages-tuple", [SimpleNamespace(type="ai", content="sync delta")])
                yield ("end", {"usage_metadata": {"total_tokens": 2}})

            return raw_stream()

    adapter = DeerFlowClientAdapter(mode="embedded", client=FakeClient())

    async def collect():
        heartbeat = []
        collected = []

        async def ticker():
            await asyncio.sleep(0)
            heartbeat.append("tick")

        async def consume():
            async for event in adapter.stream(run_id="run_1", task_id="task_1", skill="risk-officer", message="分析 AAPL", context={}):
                collected.append(event)

        await asyncio.gather(asyncio.create_task(consume()), asyncio.create_task(ticker()))
        return heartbeat, collected

    heartbeat, collected = asyncio.run(collect())
    assert heartbeat == ["tick"]
    assert [event["type"] for event in collected] == ["partial_answer", "final"]
    assert collected[-1]["payload"]["usage"] == {"total_tokens": 2}


def test_adapter_sync_stream_uses_bounded_async_queue(monkeypatch):
    created_maxsizes = []
    real_queue = asyncio.Queue

    def tracking_queue(*, maxsize=0):
        created_maxsizes.append(maxsize)
        return real_queue(maxsize=maxsize)

    monkeypatch.setattr("backend.agent_runtime.deerflow_client.asyncio.Queue", tracking_queue)

    class FakeClient:
        def stream(self, **kwargs):
            def raw_stream():
                yield ("messages-tuple", [SimpleNamespace(type="ai", content="sync delta")])
                yield ("end", {"usage_metadata": {"total_tokens": 2}})

            return raw_stream()

    adapter = DeerFlowClientAdapter(mode="embedded", client=FakeClient())

    async def collect():
        return [
            event
            async for event in adapter.stream(
                run_id="run_1",
                task_id="task_1",
                skill="risk-officer",
                message="分析 AAPL",
                context={},
            )
        ]

    events = asyncio.run(collect())
    assert [event["type"] for event in events] == ["partial_answer", "final"]
    assert created_maxsizes == [SYNC_STREAM_QUEUE_MAXSIZE]
    assert SYNC_STREAM_QUEUE_MAXSIZE == 64


def test_adapter_startup_failure_falls_back_to_stub_once():
    class FakeClient:
        def stream(self, **kwargs):
            def raw_stream():
                raise RuntimeError("sync startup failed")
                yield None  # pragma: no cover

            raw = raw_stream()
            # Force generator to start executing immediately so the error
            # is raised synchronously inside self.client.stream()
            try:
                next(raw)
            except RuntimeError:
                raise RuntimeError("sync startup failed")

    adapter = DeerFlowClientAdapter(mode="embedded", client=FakeClient())

    async def collect():
        return [
            event
            async for event in adapter.stream(
                run_id="run_1",
                task_id="task_1",
                skill="risk-officer",
                message="分析 AAPL",
                context={"symbol": "AAPL"},
            )
        ]

    events = asyncio.run(collect())
    assert [event["type"] for event in events] == ["reasoning", "final"]
    assert adapter.status().to_dict()["active_client"] == "stub"
    assert adapter.status().to_dict()["degraded"] is True
    assert "sync startup failed" in adapter.status().to_dict()["degraded_reason"]


def test_adapter_mid_stream_failure_returns_error_and_final_without_stub_second_answer():
    class FakeClient:
        async def stream(self, **kwargs):
            yield ("messages-tuple", [SimpleNamespace(type="ai", content="first partial")])
            raise RuntimeError("mid stream broke")

    adapter = DeerFlowClientAdapter(mode="embedded", client=FakeClient())

    async def collect():
        return [
            event
            async for event in adapter.stream(
                run_id="run_1",
                task_id="task_1",
                skill="risk-officer",
                message="分析 AAPL",
                context={},
            )
        ]

    events = asyncio.run(collect())
    assert [event["type"] for event in events] == ["partial_answer", "error", "final"]
    assert events[1]["payload"]["stage"] == "embedded_stream"
    assert "mid stream broke" in events[1]["payload"]["error"]
    assert events[2]["payload"]["runtime_error"].startswith("embedded stream failed after startup")
    assert all(event["payload"].get("text") != "正在处理：分析 AAPL" for event in events if event["type"] == "partial_answer")
    assert adapter.status().to_dict()["degraded"] is True


@pytest.mark.deerflow
def test_real_deerflow_embedded_smoke_when_enabled():
    if os.getenv("WORKBENCH_DEERFLOW_REAL_TEST") != "1":
        pytest.skip("WORKBENCH_DEERFLOW_REAL_TEST != 1")
    pytest.importorskip("deerflow.client")
    if not os.getenv("WORKBENCH_DEERFLOW_CONFIG_PATH"):
        pytest.skip("WORKBENCH_DEERFLOW_CONFIG_PATH is not set")

    adapter = DeerFlowClientAdapter.from_env()
    assert adapter.status().mode in {"embedded", "stub"}
    if adapter.client is None:
        pytest.skip(json.dumps(adapter.status().to_dict(), ensure_ascii=False))

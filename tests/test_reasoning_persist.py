"""reasoning 事件必须落库，且带 phase=thinking 的思维链要能进历史。"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest

from tests.test_api import make_client, parse_sse_events


def _fake_runtime(monkeypatch, messages):
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def stream(self, **kwargs):
            yield ("values", {"messages": messages, "status": "running"})
            yield ("end", {"usage_metadata": {"total_tokens": 5}})

    deerflow_pkg = ModuleType("deerflow")
    client_mod = ModuleType("deerflow.client")
    client_mod.DeerFlowClient = FakeClient
    monkeypatch.setitem(__import__("sys").modules, "deerflow", deerflow_pkg)
    monkeypatch.setitem(__import__("sys").modules, "deerflow.client", client_mod)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")


def _ai(msg_id: str, content: str = "", *, tool_calls=None, reasoning: str | None = None):
    extra = {"reasoning_content": reasoning} if reasoning else {}
    return SimpleNamespace(
        type="ai", id=msg_id, content=content, additional_kwargs=extra,
        tool_calls=tool_calls or [],
    )


def test_thinking_reasoning_is_persisted(tmp_path, monkeypatch):
    messages = [
        _ai("m1", "", tool_calls=[{"id": "c1", "name": "get_stock_context", "args": {"symbol": "BTC"}}],
            reasoning="先看现货价格，再判断合约拥挤度"),
    ]
    _fake_runtime(monkeypatch, messages)
    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={"message": "BTC 现在多少钱", "page": "chat", "authority_level": "A2"},
    ).json()
    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as resp:
        body = "".join(resp.iter_text())

    events = [e for e in parse_sse_events(body) if e["type"] == "reasoning"]
    assert any("先看现货价格" in str(e["payload"]) for e in events), "SSE 里应带思维链"

    stored = client.app.state.services.repo.list_copilot_messages(session_id=run["session_id"])
    reasoning = [m for m in stored if m.kind == "reasoning"]
    assert reasoning, "reasoning 必须落库，否则历史对话看不到思考"
    assert any("先看现货价格" in str(m.payload.get("text") or "") for m in reasoning)


def test_values_answer_text_is_not_persisted_as_reasoning(tmp_path, monkeypatch):
    """纯文本 AI 消息是答案，不能落成 reasoning（否则历史里「思考」= 答案开头）。"""
    messages = [_ai("m1", "**结论：TRX 过去一年横盘**")]
    _fake_runtime(monkeypatch, messages)
    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={"message": "TRX 趋势", "page": "chat", "authority_level": "A2"},
    ).json()
    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as resp:
        "".join(resp.iter_text())

    stored = client.app.state.services.repo.list_copilot_messages(session_id=run["session_id"])
    reasoning = [m for m in stored if m.kind == "reasoning"]
    assert all("TRX 过去一年横盘" not in str(m.payload.get("text") or "") for m in reasoning)

"""Cooperative cancel of an in-flight copilot stream_run."""

from __future__ import annotations

import asyncio

import pytest

from backend.bootstrap import create_services
from backend.schemas import CopilotSessionCreateRequest, CopilotSessionMessageRequest


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SKIP_SEED", "1")
    monkeypatch.setenv("WORKBENCH_AI_MODE", "stub")
    return create_services(db_path=tmp_path / "cancel.sqlite3", files_root=tmp_path / "files")


def test_cancel_run_idempotent_when_not_running(services):
    result = services.copilot_service.cancel_run("missing-run-id")
    assert result["status"] == "not_running"
    assert result["run_id"] == "missing-run-id"


def test_cancel_run_sets_flag_for_active_run(services):
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="cancel-flag", current_page="chat")
    )
    run = services.copilot_service.create_session_run(
        session.session_id,
        CopilotSessionMessageRequest(message="hello", page="chat", symbol=""),
    )
    assert run.run_id in services.copilot_service._runs

    status = services.copilot_service.cancel_run(run.run_id, session_id=session.session_id)
    assert status["status"] == "cancelling"
    assert status.get("alive") is True
    assert services.copilot_service._is_run_cancelled(run.run_id)

    live = services.copilot_service.get_run_status(run.run_id, session_id=session.session_id)
    assert live["status"] == "cancelling"
    assert live["alive"] is True

    services.copilot_service._runs.pop(run.run_id, None)
    services.copilot_service._cancelled_runs.discard(run.run_id)
    again = services.copilot_service.cancel_run(run.run_id, session_id=session.session_id)
    assert again["status"] == "not_running"


def test_get_run_status_tracks_tool_phase(services, monkeypatch):
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="status-phase", current_page="chat")
    )
    run = services.copilot_service.create_session_run(
        session.session_id,
        CopilotSessionMessageRequest(message="hello", page="chat", symbol=""),
    )

    async def toolish_stream(**kwargs):
        yield {
            "type": "tool_call",
            "payload": {"tool": "web_search", "call_id": "c1", "arguments": {}},
        }
        yield {
            "type": "tool_result",
            "payload": {"tool": "web_search", "call_id": "c1", "result": "ok"},
        }
        yield {
            "type": "final",
            "payload": {"conclusion": "done"},
        }

    monkeypatch.setattr(services.copilot_service.deerflow, "stream", toolish_stream)

    async def collect():
        events = []
        saw_tool_progress = False
        async for event in services.copilot_service.stream_run(
            run.run_id, session_id=session.session_id
        ):
            events.append(event)
            if event.type == "progress" and event.payload.get("phase") == "tool":
                saw_tool_progress = True
                assert event.payload.get("current_tool") == "web_search"
                assert event.payload.get("alive") is True
        return events, saw_tool_progress

    events, saw_tool_progress = asyncio.run(collect())
    types = [e.type for e in events]
    assert "progress" in types
    assert "tool_call" in types
    assert "final" in types
    assert saw_tool_progress is True

    after = services.copilot_service.get_run_status(run.run_id, session_id=session.session_id)
    assert after["alive"] is False
    assert after["status"] in {"completed", "not_running"}


def test_run_status_api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SKIP_SEED", "1")
    monkeypatch.setenv("WORKBENCH_AI_MODE", "stub")
    from fastapi.testclient import TestClient

    from backend.app import create_app

    app = create_app(db_path=tmp_path / "status_api.sqlite3", files_root=tmp_path / "files")
    client = TestClient(app)
    session = client.post("/api/copilot/sessions", json={"title": "api-status"}).json()
    run = client.post(
        f"/api/copilot/sessions/{session['session_id']}/messages",
        json={"message": "hi", "page": "chat", "symbol": ""},
    ).json()
    resp = client.get(
        f"/api/copilot/sessions/{session['session_id']}/runs/{run['run_id']}/status"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run["run_id"]
    assert "alive" in body
    assert "status" in body


def test_stream_run_honours_cancel_flag(services, monkeypatch):
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="cancel-stream", current_page="chat")
    )
    run = services.copilot_service.create_session_run(
        session.session_id,
        CopilotSessionMessageRequest(message="hello", page="chat", symbol=""),
    )

    async def slow_stream(**kwargs):
        yield {
            "type": "reasoning",
            "payload": {"text": "thinking"},
        }
        yield {
            "type": "partial_answer",
            "payload": {"text": "partial"},
        }

    monkeypatch.setattr(services.copilot_service.deerflow, "stream", slow_stream)
    services.copilot_service.cancel_run(run.run_id, session_id=session.session_id)

    async def collect():
        return [
            event
            async for event in services.copilot_service.stream_run(
                run.run_id, session_id=session.session_id
            )
        ]

    events = asyncio.run(collect())
    types = [e.type for e in events]
    assert "error" in types
    assert "final" in types
    err = next(e for e in events if e.type == "error")
    assert err.payload.get("stage") == "user_cancel"


def test_cancel_session_run_api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SKIP_SEED", "1")
    monkeypatch.setenv("WORKBENCH_AI_MODE", "stub")
    from fastapi.testclient import TestClient

    from backend.app import create_app

    app = create_app(db_path=tmp_path / "cancel_api.sqlite3", files_root=tmp_path / "files")
    client = TestClient(app)
    session = client.post("/api/copilot/sessions", json={"title": "api-cancel"}).json()
    run = client.post(
        f"/api/copilot/sessions/{session['session_id']}/messages",
        json={"message": "hi", "page": "chat", "symbol": ""},
    ).json()
    resp = client.post(
        f"/api/copilot/sessions/{session['session_id']}/runs/{run['run_id']}/cancel"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in {"cancelling", "not_running"}

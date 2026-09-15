from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.access_auth import is_sse_path, tokens_match


def _client(tmp_path):
    app = create_app(db_path=tmp_path / "api.sqlite3", files_root=tmp_path / "files")
    return TestClient(app)


def test_tokens_match_rejects_length_mismatch():
    assert tokens_match("abc", "abc") is True
    assert tokens_match("abc", "abcd") is False
    assert tokens_match("", "secret") is False


def test_sse_path_detection():
    assert is_sse_path("/api/monitor/stream") is True
    assert is_sse_path("/api/copilot/stream/run-1") is True
    assert is_sse_path("/api/copilot/sessions/s1/stream/r1") is True
    assert is_sse_path("/api/copilot/sessions") is False
    assert is_sse_path("/api/watchlist") is False


def test_no_token_keeps_open_api(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_ACCESS_TOKEN", raising=False)
    client = _client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["agent_runtime"]
    assert client.get("/api/copilot/sessions").status_code == 200


def test_token_limits_health_and_blocks_api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_ACCESS_TOKEN", "s3cret-token")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "stub")
    client = _client(tmp_path)

    public = client.get("/api/health")
    assert public.status_code == 200
    assert public.json() == {"status": "ok", "server_role": "workbench"}

    blocked = client.get("/api/copilot/sessions")
    assert blocked.status_code == 401

    query_blocked = client.get("/api/copilot/sessions?access_token=s3cret-token")
    assert query_blocked.status_code == 401

    ok = client.get("/api/copilot/sessions", headers={"X-Workbench-Token": "s3cret-token"})
    assert ok.status_code == 200

    bearer = client.get("/api/copilot/sessions", headers={"Authorization": "Bearer s3cret-token"})
    assert bearer.status_code == 200

    full_health = client.get("/api/health", headers={"X-Workbench-Token": "s3cret-token"})
    assert full_health.status_code == 200
    assert full_health.json()["agent_runtime"]["active_client"]


def test_sse_accepts_query_token(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_ACCESS_TOKEN", "s3cret-token")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "stub")
    client = _client(tmp_path)
    denied = client.get("/api/monitor/stream?once=true")
    assert denied.status_code == 401
    allowed = client.get("/api/monitor/stream?once=true&access_token=s3cret-token")
    assert allowed.status_code == 200
    assert "text/event-stream" in allowed.headers.get("content-type", "")

from __future__ import annotations

from types import SimpleNamespace

from backend.app_services.setup_service import finish_setup, setup_status
from backend.schemas import CopilotMessage, CopilotSessionCreateRequest
from tests.test_api import _force_stub_runtime, make_client


class _FakeRepo:
    def __init__(self, *, sessions=None, setup=None):
        self._sessions = list(sessions or [])
        self._config = {}
        if setup is not None:
            self._config["setup"] = setup

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def set_config(self, key, payload):
        self._config[key] = payload
        return payload

    def list_copilot_sessions(self, limit=100):
        return self._sessions[:limit]


def test_setup_status_requires_fresh_workspace():
    status = setup_status(_FakeRepo(), {"connected": [], "runtime": {"connected": False}})
    assert status["required"] is True
    assert status["completed"] is False


def test_setup_status_skips_when_already_completed():
    status = setup_status(
        _FakeRepo(setup={"completed": True}),
        {"connected": [], "runtime": {"connected": False}},
    )
    assert status["required"] is False
    assert status["completed"] is True


def test_setup_status_grandfathers_workspace_with_chat():
    repo = _FakeRepo(sessions=[SimpleNamespace(last_message_at="2026-09-08T01:00:00Z", message_count=1)])
    status = setup_status(repo, {"connected": [], "runtime": {"connected": False}})
    assert status["required"] is False
    assert status["completed"] is True
    assert repo.get_config("setup")["grandfathered"] is True


def test_setup_status_ignores_empty_sessions_without_messages():
    repo = _FakeRepo(sessions=[SimpleNamespace(last_message_at=None, message_count=0)])
    status = setup_status(repo, {"connected": [{"id": "deepseek"}], "default_model": "deepseek/chat"})
    assert status["required"] is True
    assert status["model_connected"] is True


def test_setup_required_on_fresh_workspace(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    payload = client.get("/api/setup").json()
    assert payload["required"] is True
    assert payload["completed"] is False


def test_setup_finish_seeds_demo_and_keeps_paid_sources_off(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    repo = client.app.state.services.repo
    data_sources = dict(repo.get_config("data_sources") or {})
    states = dict(data_sources.get("provider_states") or {})
    states["tushare"] = {"enabled": True}
    states["tickflow"] = {"enabled": True}
    states["longbridge"] = {"enabled": True}
    data_sources["provider_states"] = states
    repo.set_config("data_sources", data_sources)
    for holding in list(repo.list_holdings()):
        repo.delete_holding(holding.symbol)

    payload = client.post("/api/setup/finish").json()
    assert payload["completed"] is True
    assert payload["required"] is False
    assert payload["demo"] is False
    finished_states = (payload.get("data_sources") or {}).get("provider_states") or {}
    assert finished_states["tushare"]["enabled"] is False
    assert finished_states["tickflow"]["enabled"] is False
    assert finished_states["longbridge"]["enabled"] is False
    assert finished_states["eastmoney"]["enabled"] is True
    assert finished_states["yfinance"]["enabled"] is True
    assert repo.list_holdings() == []

    again = client.get("/api/setup").json()
    assert again["required"] is False
    assert again["completed"] is True


def test_setup_grandfathers_workspace_with_saved_chat(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    services = client.app.state.services
    session = services.copilot_service.create_session(CopilotSessionCreateRequest(title="已有对话"))
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="msg_setup_existing",
            session_id=session.session_id,
            role="user",
            kind="user_message",
            text="已经聊过",
        )
    )
    payload = client.get("/api/setup").json()
    assert payload["required"] is False
    assert payload["completed"] is True
    stored = services.repo.get_config("setup")
    assert stored["grandfathered"] is True


def test_finish_setup_helper_marks_completed(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    result = finish_setup(client.app.state.services.repo)
    assert result["completed"] is True
    assert result["demo"] is False

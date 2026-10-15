from __future__ import annotations

from tests.test_api import make_client


def test_session_default_model_persists_and_updates(tmp_path):
    client = make_client(tmp_path)
    connected = client.post("/api/settings/llm/connect", json={
        "provider_id": "deepseek",
        "api_key": "sk-session-model",
    })
    assert connected.status_code == 200
    global_default = connected.json()["default_model"]

    session = client.post("/api/copilot/sessions", json={
        "title": "模型会话",
        "default_model": global_default,
    }).json()
    assert session["default_model"] == global_default

    catalog = connected.json()["catalog"]
    deepseek = next(item for item in catalog if item["id"] == "deepseek")
    alt_model = deepseek["models"][1]["id"] if len(deepseek["models"]) > 1 else deepseek["models"][0]["id"]
    alt_ref = f"deepseek/{alt_model}"

    updated = client.put(
        f"/api/copilot/sessions/{session['session_id']}",
        json={"default_model": alt_ref},
    )
    assert updated.status_code == 200
    assert updated.json()["default_model"] == alt_ref

    detail = client.get(f"/api/copilot/sessions/{session['session_id']}").json()
    assert detail["default_model"] == alt_ref


def test_reconnect_with_slot_keeps_session_model(tmp_path, monkeypatch):
    from backend.app_services.copilot_service import CopilotService
    from backend.bootstrap import create_services

    services = create_services(db_path=tmp_path / "slot.sqlite3", files_root=tmp_path / "files")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "stub")
    slot = {
        "api_key": "sk-session",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-v4-flash",
        "provider_id": "deepseek",
    }
    status = services.copilot_service._reconnect_with_slot(slot)
    assert services.copilot_service.deerflow.model_name == "deepseek-v4-flash"
    assert status["model_name"] == "deepseek-v4-flash"

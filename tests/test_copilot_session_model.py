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

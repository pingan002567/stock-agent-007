from __future__ import annotations

import json
import os

import pytest

from backend.config.credentials import (
    effective_runtime_config,
    load_llm_credentials,
)
from backend.config.llm_catalog import match_provider_by_base_url
from tests.test_api import make_client

_LLM_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "WORKBENCH_AI_MODEL", "WORKBENCH_AI_API_KEY")


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in (
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "MIMO_API_KEY",
        "ZHIPUAI_API_KEY",
        "ZAI_API_KEY",
        "KIMI_API_KEY",
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
        "SILICONFLOW_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_match_provider_by_base_url():
    assert match_provider_by_base_url("https://api.deepseek.com") == "deepseek"
    assert match_provider_by_base_url("https://api.deepseek.com/v1") == "deepseek"
    assert match_provider_by_base_url("https://api.moonshot.cn/v1") == "kimi"
    assert match_provider_by_base_url("https://open.bigmodel.cn/api/paas/v4") == "zhipu"
    assert match_provider_by_base_url("https://api.xiaomimimo.com/v1") == "mimo"
    assert match_provider_by_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1") == "qwen"
    assert match_provider_by_base_url("https://api.openai.com/v1") == "openai"
    assert match_provider_by_base_url("https://unknown.example/v1") is None


def test_legacy_credentials_migrate_to_catalog_provider(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    monkeypatch.setenv("WORKBENCH_CREDENTIALS_PATH", str(cred))
    cred.write_text(json.dumps({
        "api_key": "sk-legacy-deepseek",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
    }), encoding="utf-8")
    data = load_llm_credentials()
    assert data["providers"]["deepseek"]["api_key"] == "sk-legacy-deepseek"
    assert data["default_model"] == "deepseek/deepseek-chat"
    saved = json.loads(cred.read_text(encoding="utf-8"))
    assert saved["default_model"] == "deepseek/deepseek-chat"


def test_legacy_unknown_url_becomes_custom(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    monkeypatch.setenv("WORKBENCH_CREDENTIALS_PATH", str(cred))
    cred.write_text(json.dumps({
        "api_key": "sk-proxy",
        "base_url": "https://llm.acme.example/v1",
        "model_name": "qwen-plus",
    }), encoding="utf-8")
    data = load_llm_credentials()
    assert "legacy" in data["custom_providers"]
    assert data["default_model"] == "legacy/qwen-plus"
    assert data["providers"]["legacy"]["api_key"] == "sk-proxy"


def test_env_vars_do_not_auto_connect_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")
    client = make_client(tmp_path)
    snap = client.get("/api/settings/llm/providers").json()
    connected_ids = {item["id"] for item in snap["connected"]}
    assert "deepseek" not in connected_ids
    deepseek = next(item for item in snap["catalog"] if item["id"] == "deepseek")
    assert deepseek["connected"] is False
    assert deepseek["source"] is None


def test_connect_then_effective_runtime_writes_openai_env(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    created = client.post("/api/settings/llm/connect", json={
        "provider_id": "deepseek",
        "api_key": "sk-connected",
    })
    assert created.status_code == 200
    body = created.json()
    assert any(item["id"] == "deepseek" for item in body["connected"])
    assert body["default_model"] == "deepseek/deepseek-v4-flash"
    connected_model_refs = {
        f"{item['id']}/{model['id']}"
        for item in body["connected"]
        for model in item["models"]
    }
    catalog_unconnected = {item["id"] for item in body["catalog"] if not item["connected"]}
    assert "openai" in catalog_unconnected
    assert "openai/gpt-4o" not in connected_model_refs

    blocked = client.put("/api/settings/llm/default-model", json={"default_model": "openai/gpt-4o"})
    assert blocked.status_code == 400

    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "direct")
    cfg = effective_runtime_config(client.app.state.services.repo)
    assert cfg["api_key"] == "sk-connected"
    assert "deepseek.com" in (cfg.get("base_url") or "")
    assert cfg["model_name"] == "deepseek-v4-flash"
    assert os.environ.get("OPENAI_API_KEY") == "sk-connected"
    assert os.environ.get("WORKBENCH_AI_MODEL") == "deepseek-v4-flash"


def test_custom_provider_validation(tmp_path):
    client = make_client(tmp_path)
    missing_models = client.post("/api/settings/llm/custom", json={
        "id": "acme",
        "name": "Acme",
        "base_url": "https://llm.acme.example/v1",
        "models": [],
    })
    assert missing_models.status_code == 400

    builtin = client.post("/api/settings/llm/custom", json={
        "id": "deepseek",
        "name": "Nope",
        "base_url": "https://llm.acme.example/v1",
        "models": [{"id": "x", "name": "X"}],
    })
    assert builtin.status_code == 400

    bad_id = client.post("/api/settings/llm/custom", json={
        "id": "Acme Cloud",
        "name": "Acme",
        "base_url": "https://llm.acme.example/v1",
        "models": [{"id": "x", "name": "X"}],
    })
    assert bad_id.status_code == 400

    ok = client.post("/api/settings/llm/custom", json={
        "id": "acme",
        "name": "Acme",
        "base_url": "https://llm.acme.example/v1",
        "api_key": "sk-acme",
        "models": [{"id": "qwen3", "name": "Qwen 3"}],
        "headers": [{"key": "X-App", "value": "stock-agent"}],
    })
    assert ok.status_code == 200
    acme = next(item for item in ok.json()["connected"] if item["id"] == "acme")
    assert acme["custom"] is True
    assert acme["source"] == "custom"
    assert acme["models"][0]["id"] == "qwen3"


def test_ollama_connect_without_key(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/settings/llm/connect", json={"provider_id": "ollama"})
    assert created.status_code == 200
    ollama = next(item for item in created.json()["connected"] if item["id"] == "ollama")
    assert ollama["requires_key"] is False


def test_settings_payload_includes_llm_providers(tmp_path):
    client = make_client(tmp_path)
    settings = client.get("/api/settings").json()
    assert "llm_providers" in settings
    assert "catalog" in settings["llm_providers"]
    catalog_ids = {item["id"] for item in settings["llm_providers"]["catalog"]}
    for provider_id in ("deepseek", "kimi", "qwen", "zhipu", "mimo"):
        assert provider_id in catalog_ids


def test_moonshot_credentials_migrate_to_kimi(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    monkeypatch.setenv("WORKBENCH_CREDENTIALS_PATH", str(cred))
    cred.write_text(json.dumps({
        "providers": {"moonshot": {"api_key": "sk-kimi", "source": "api"}},
        "default_model": "moonshot/kimi-k2.5",
    }), encoding="utf-8")
    data = load_llm_credentials()
    assert "moonshot" not in data["providers"]
    assert data["providers"]["kimi"]["api_key"] == "sk-kimi"
    assert data["default_model"] == "kimi/kimi-k2.5"


def test_llm_snapshot_does_not_echo_secrets(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/settings/llm/connect", json={
        "provider_id": "deepseek",
        "api_key": "sk-secret-value-do-not-echo",
    })
    assert created.status_code == 200
    body = created.json()
    snap_text = json.dumps(body)
    assert "sk-secret-value-do-not-echo" not in snap_text
    deepseek = next(item for item in body["connected"] if item["id"] == "deepseek")
    assert deepseek["has_key"] is True
    settings = client.get("/api/settings").json()
    assert "sk-secret-value-do-not-echo" not in json.dumps(settings)
    assert settings["runtime_config"].get("api_key") in (None, "")


def test_ambient_env_does_not_synthesize_runtime_without_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "direct")
    client = make_client(tmp_path)
    cfg = effective_runtime_config(client.app.state.services.repo)
    assert not cfg.get("api_key")
    assert not cfg.get("base_url")
    assert not cfg.get("model_name")

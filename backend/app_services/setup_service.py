"""工作区「开始使用」完成态：新文件夹走向导，老工作区自动视为已完成。"""
from __future__ import annotations

from typing import Any

from backend.config.data_source_sanitize import sanitize_data_sources
from backend.config.data_sources import AVAILABLE_PROVIDERS, DEFAULT_DATA_SOURCES
from backend.config.provider_policy import is_free_provider, merge_provider_states
from backend.schemas import now_iso

SETUP_CONFIG_KEY = "setup"


def _session_has_chat(session: Any) -> bool:
    return bool(getattr(session, "last_message_at", None) or (getattr(session, "message_count", 0) or 0) > 0)


def _has_connected_model(llm_snapshot: dict[str, Any]) -> bool:
    connected = llm_snapshot.get("connected") or []
    runtime = llm_snapshot.get("runtime") or {}
    return bool(connected) or bool(runtime.get("connected"))


def _workspace_has_chats(repo) -> bool:
    sessions = repo.list_copilot_sessions(limit=100)
    return any(_session_has_chat(item) for item in sessions)


def apply_free_data_source_defaults(repo) -> dict[str, Any]:
    raw = repo.get_config("data_sources", DEFAULT_DATA_SOURCES) or dict(DEFAULT_DATA_SOURCES)
    cleaned = sanitize_data_sources(dict(raw))
    states = merge_provider_states(cleaned)
    for item in AVAILABLE_PROVIDERS:
        pid = str(item["id"])
        states[pid] = {"enabled": is_free_provider(pid)}
    cleaned["provider_states"] = states
    return repo.set_config("data_sources", cleaned)


def mark_setup_completed(repo, *, grandfathered: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "completed": True,
        "completed_at": now_iso(),
    }
    if grandfathered:
        payload["grandfathered"] = True
    repo.set_config(SETUP_CONFIG_KEY, payload)
    return payload


def setup_status(repo, llm_snapshot: dict[str, Any]) -> dict[str, Any]:
    stored = dict(repo.get_config(SETUP_CONFIG_KEY, {}) or {})
    model_connected = _has_connected_model(llm_snapshot)
    default_model = llm_snapshot.get("default_model") or (llm_snapshot.get("runtime") or {}).get("default_model")

    if stored.get("completed"):
        return {
            "completed": True,
            "required": False,
            "model_connected": model_connected,
            "default_model": default_model,
        }

    if _workspace_has_chats(repo):
        mark_setup_completed(repo, grandfathered=True)
        return {
            "completed": True,
            "required": False,
            "model_connected": model_connected,
            "default_model": default_model,
        }

    return {
        "completed": False,
        "required": True,
        "model_connected": model_connected,
        "default_model": default_model,
    }


def finish_setup(repo) -> dict[str, Any]:
    repo.seed_defaults()
    data_sources = apply_free_data_source_defaults(repo)
    setup = mark_setup_completed(repo)
    return {
        "completed": True,
        "required": False,
        "demo": repo.is_demo_portfolio(),
        "setup": setup,
        "data_sources": data_sources,
    }

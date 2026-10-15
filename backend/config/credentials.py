"""用户级 AI 凭证（跨工作区共享，状态目录 ``credentials.json``）。

分层语义（密钥跟人、偏好跟档案）：

    档案 DB 的 runtime 配置（非空字段，档案级覆盖）
      > credentials.json（多提供商 + default_model）

兼容旧三字段 ``api_key / base_url / model_name``：读取时迁移进
``providers`` / ``custom_providers`` / ``default_model``，并继续回写
合成后的单槽给 DeerFlow（OPENAI_API_KEY / OPENAI_BASE_URL / WORKBENCH_AI_MODEL）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend import paths
from backend.config.llm_catalog import (
    LLM_CATALOG,
    first_model_id,
    format_model_ref,
    get_provider_spec,
    match_provider_by_base_url,
    parse_model_ref,
)
from backend.config.runtime import DEFAULT_RUNTIME_CONFIG

# 旧单槽键：PUT /runtime 与迁移仍认这些字段
CRED_KEYS = ("api_key", "base_url", "model_name")

_PLACEHOLDERS = {"your_api_key_here", "sk-xxx", "xxx", ""}
_LEGACY_ID = "legacy"


def credentials_path() -> Path:
    override = os.getenv("WORKBENCH_CREDENTIALS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return paths.service_state_dir() / "credentials.json"


def load_credentials() -> dict[str, Any]:
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def persist_credentials(data: dict[str, Any]) -> dict[str, Any]:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


def _clean_secret(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped in _PLACEHOLDERS:
        return None
    return stripped


def migrate_legacy_credentials(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """把旧三字段迁进多提供商结构。已是新格式则原样返回。"""
    current = dict(data)
    changed = False
    providers = current.get("providers")
    custom = current.get("custom_providers")
    has_new = isinstance(providers, dict) or isinstance(custom, dict)
    api_key = _clean_secret(current.get("api_key"))
    base_url = (current.get("base_url") or "").strip() or None
    model_name = (current.get("model_name") or "").strip() or None

    if not has_new and (api_key or base_url or model_name):
        current["providers"] = {} if not isinstance(providers, dict) else dict(providers)
        current["custom_providers"] = {} if not isinstance(custom, dict) else dict(custom)
        provider_id = match_provider_by_base_url(base_url) if base_url else None
        if provider_id is None and api_key:
            provider_id = _LEGACY_ID
        if provider_id == _LEGACY_ID:
            model_id = model_name or "default"
            current["custom_providers"][_LEGACY_ID] = {
                "name": "已保存连接",
                "base_url": base_url or "",
                "models": [{"id": model_id, "name": model_id}],
                "headers": {},
            }
            if api_key:
                current["providers"][_LEGACY_ID] = {"api_key": api_key, "source": "api"}
            current["default_model"] = format_model_ref(_LEGACY_ID, model_id)
        elif provider_id:
            spec = get_provider_spec(provider_id)
            model_id = model_name or (first_model_id(spec) if spec else "default")
            if api_key:
                current["providers"][provider_id] = {"api_key": api_key, "source": "api"}
            current["default_model"] = format_model_ref(provider_id, model_id)
        elif model_name:
            current["default_model"] = model_name
        changed = True

    if "providers" not in current or not isinstance(current.get("providers"), dict):
        current["providers"] = {}
        changed = True
    if "custom_providers" not in current or not isinstance(current.get("custom_providers"), dict):
        current["custom_providers"] = {}
        changed = True
    return current, changed


_PROVIDER_ALIASES: dict[str, str] = {
    "moonshot": "kimi",
}


def migrate_provider_aliases(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """把已废弃的内置提供商 ID 迁到新 ID（如 moonshot → kimi）。"""
    current = dict(data)
    changed = False
    providers = dict(current.get("providers") or {})
    for old_id, new_id in _PROVIDER_ALIASES.items():
        if old_id in providers and new_id not in providers:
            providers[new_id] = providers.pop(old_id)
            changed = True
    if changed:
        current["providers"] = providers
    default = str(current.get("default_model") or "")
    for old_id, new_id in _PROVIDER_ALIASES.items():
        prefix = f"{old_id}/"
        if default.startswith(prefix):
            current["default_model"] = format_model_ref(new_id, default[len(prefix):])
            changed = True
            break
    return current, changed


def _provider_model_ids(data: dict[str, Any], provider_id: str) -> list[str]:
    spec = get_provider_spec(provider_id)
    if spec:
        return [m.id for m in spec.models]
    custom = custom_provider(data, provider_id)
    if not custom:
        return []
    return [
        str(m.get("id"))
        for m in (custom.get("models") or [])
        if isinstance(m, dict) and m.get("id")
    ]


def migrate_invalid_default_model(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """修正 default_model 指向错误提供商或不存在模型的情况（如 deepseek/mimo-v2.5）。"""
    current = dict(data)
    default = str(current.get("default_model") or "").strip()
    if not default:
        return current, False
    provider_id, model_id = parse_model_ref(default)
    if not provider_id or not model_id:
        return current, False

    connected = list_connected_ids(current)
    if provider_id not in connected:
        if not connected:
            return current, False
        pid = connected[0]
        ids = _provider_model_ids(current, pid)
        if not ids:
            return current, False
        current["default_model"] = format_model_ref(pid, ids[0])
        return current, True

    model_ids = _provider_model_ids(current, provider_id)
    if model_id in model_ids:
        return current, False

    for pid in connected:
        ids = _provider_model_ids(current, pid)
        if model_id in ids:
            current["default_model"] = format_model_ref(pid, model_id)
            return current, True

    if model_ids:
        current["default_model"] = format_model_ref(provider_id, model_ids[0])
        return current, True
    if connected:
        pid = connected[0]
        ids = _provider_model_ids(current, pid)
        if ids:
            current["default_model"] = format_model_ref(pid, ids[0])
            return current, True
    return current, False


def load_llm_credentials() -> dict[str, Any]:
    data, changed = migrate_legacy_credentials(load_credentials())
    data, alias_changed = migrate_provider_aliases(data)
    data, model_changed = migrate_invalid_default_model(data)
    changed = changed or alias_changed or model_changed
    if changed and credentials_path().exists():
        persist_credentials(data)
    return data


def save_credentials(update: dict[str, Any]) -> dict[str, Any]:
    """合并写入。仍接受旧 CRED_KEYS；同时可写 providers / custom_providers / default_model。"""
    current, _ = migrate_legacy_credentials(load_credentials())
    for key in CRED_KEYS:
        if key not in update:
            continue
        raw = update.get(key)
        if isinstance(raw, str) and raw.strip() and raw.strip() not in _PLACEHOLDERS:
            current[key] = raw.strip()

    if any(k in update for k in ("api_key", "base_url", "model_name")):
        _apply_legacy_slot(current, update)

    if "providers" in update and isinstance(update["providers"], dict):
        current["providers"] = dict(update["providers"])
    if "custom_providers" in update and isinstance(update["custom_providers"], dict):
        current["custom_providers"] = dict(update["custom_providers"])
    if "default_model" in update:
        raw = update.get("default_model")
        current["default_model"] = str(raw).strip() if raw else None

    return persist_credentials(current)


def _apply_legacy_slot(current: dict[str, Any], update: dict[str, Any]) -> None:
    api_key = _clean_secret(update.get("api_key")) or _clean_secret(current.get("api_key"))
    base_url = ""
    if update.get("base_url") not in (None, ""):
        base_url = str(update.get("base_url")).strip()
    else:
        base_url = str(current.get("base_url") or "").strip()
    model_name = ""
    if update.get("model_name") not in (None, ""):
        model_name = str(update.get("model_name")).strip()
    else:
        model_name = str(current.get("model_name") or "").strip()
    if not api_key and not base_url:
        return
    providers = current.setdefault("providers", {})
    custom = current.setdefault("custom_providers", {})
    provider_id = match_provider_by_base_url(base_url) if base_url else None
    if provider_id is None:
        provider_id = _LEGACY_ID
        model_id = model_name or "default"
        custom[_LEGACY_ID] = {
            "name": "已保存连接",
            "base_url": base_url,
            "models": [{"id": model_id, "name": model_id}],
            "headers": {},
        }
    else:
        spec = get_provider_spec(provider_id)
        model_id = model_name or (first_model_id(spec) if spec else "default")
    if api_key:
        providers[provider_id] = {"api_key": api_key, "source": "api"}
    if not current.get("default_model") and model_id:
        current["default_model"] = format_model_ref(provider_id, model_id)
    if api_key:
        current["api_key"] = api_key
    if base_url:
        current["base_url"] = base_url
    if model_name:
        current["model_name"] = model_name


def ensure_credentials() -> None:
    """首次落盘（幂等）：仅迁移旧格式 credentials.json。"""
    if os.getenv("WORKBENCH_DEERFLOW_MODE") == "stub":
        return
    if not credentials_path().exists():
        return
    data, changed = migrate_legacy_credentials(load_credentials())
    if changed:
        persist_credentials(data)


def stored_provider_key(data: dict[str, Any], provider_id: str) -> str | None:
    block = (data.get("providers") or {}).get(provider_id)
    if not isinstance(block, dict):
        return None
    return _clean_secret(block.get("api_key"))


def provider_connection_source(data: dict[str, Any], provider_id: str, *, requires_key: bool) -> str | None:
    stored = stored_provider_key(data, provider_id)
    custom = (data.get("custom_providers") or {}).get(provider_id)
    if stored:
        return "custom" if isinstance(custom, dict) else "api"
    if isinstance(custom, dict):
        return "custom"
    block = (data.get("providers") or {}).get(provider_id)
    if isinstance(block, dict) and (not requires_key or block.get("source")):
        return str(block.get("source") or "api")
    return None


def resolve_provider_secret(data: dict[str, Any], provider_id: str) -> str | None:
    return stored_provider_key(data, provider_id)


def custom_provider(data: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    block = (data.get("custom_providers") or {}).get(provider_id)
    return dict(block) if isinstance(block, dict) else None


def list_connected_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for spec in LLM_CATALOG:
        source = provider_connection_source(data, spec.id, requires_key=spec.requires_key)
        if source:
            ids.append(spec.id)
            seen.add(spec.id)
    for pid, meta in (data.get("custom_providers") or {}).items():
        if pid in seen or not isinstance(meta, dict):
            continue
        source = provider_connection_source(data, pid, requires_key=True)
        if source:
            ids.append(str(pid))
            seen.add(str(pid))
    for pid, block in (data.get("providers") or {}).items():
        if pid in seen or not isinstance(block, dict):
            continue
        if stored_provider_key(data, pid) or block.get("source"):
            ids.append(str(pid))
    return ids


def resolve_slot(data: dict[str, Any], default_model: str | None) -> dict[str, Any]:
    """把 default_model 解析成 DeerFlow 单槽 {api_key, base_url, model_name, provider_id}。"""
    provider_id, model_id = parse_model_ref(default_model)
    if provider_id is None and default_model:
        # 裸模型名：优先匹配已连接提供商
        for pid in list_connected_ids(data):
            spec = get_provider_spec(pid)
            custom = custom_provider(data, pid)
            model_ids = [m.id for m in spec.models] if spec else [
                str(m.get("id")) for m in (custom or {}).get("models") or [] if isinstance(m, dict)
            ]
            if default_model in model_ids:
                provider_id, model_id = pid, default_model
                break
        if provider_id is None:
            connected = list_connected_ids(data)
            if connected:
                provider_id = connected[0]
                model_id = default_model

    if provider_id is None:
        connected = list_connected_ids(data)
        if connected:
            provider_id = connected[0]
            spec = get_provider_spec(provider_id)
            custom = custom_provider(data, provider_id)
            model_id = first_model_id(spec) if spec else (
                str(((custom or {}).get("models") or [{}])[0].get("id") or provider_id)
                if custom else provider_id
            )

    if provider_id is None:
        return {"api_key": None, "base_url": None, "model_name": None, "provider_id": None, "source": None}

    spec = get_provider_spec(provider_id)
    custom = custom_provider(data, provider_id)
    base_url = spec.base_url if spec else str((custom or {}).get("base_url") or "")
    if spec is None and custom:
        models = custom.get("models") or []
        if not model_id and models:
            model_id = str(models[0].get("id") or provider_id)
    elif spec and not model_id:
        model_id = first_model_id(spec)
    model_ids = _provider_model_ids(data, provider_id)
    if model_id and model_ids and model_id not in model_ids:
        model_id = model_ids[0]
    requires_key = spec.requires_key if spec else True
    source = provider_connection_source(data, provider_id, requires_key=requires_key)
    api_key = resolve_provider_secret(data, provider_id)
    if spec is None and custom:
        source = source or "custom"
    headers = {}
    if custom and isinstance(custom.get("headers"), dict):
        headers = {str(k): str(v) for k, v in custom["headers"].items() if k and v is not None}
    return {
        "api_key": api_key,
        "base_url": base_url or None,
        "model_name": model_id,
        "provider_id": provider_id,
        "source": source,
        "headers": headers,
    }


def effective_runtime_config(repo) -> dict[str, Any]:
    """分层合成 runtime 配置，并把关键值注入 env（from_env 是 env 优先）。"""
    raw = repo.get_config("runtime", {})
    workspace = raw.get("config", raw) or {}

    if os.getenv("WORKBENCH_DEERFLOW_MODE") == "stub":
        return workspace or dict(DEFAULT_RUNTIME_CONFIG)

    ensure_credentials()
    data = load_llm_credentials()
    ws_model = workspace.get("model_name") or workspace.get("default_model")
    default_model = (
        (str(ws_model).strip() if ws_model not in (None, "") else None)
        or (str(data.get("default_model")).strip() if data.get("default_model") else None)
    )
    slot = resolve_slot(data, default_model)
    creds = {
        k: slot[k]
        for k in ("api_key", "base_url", "model_name")
        if slot.get(k)
    }
    overrides = {k: v for k, v in workspace.items() if v not in (None, "")}
    merged = {**creds, **overrides}
    if slot.get("model_name") and "model_name" not in overrides:
        merged["model_name"] = slot["model_name"]
    if slot.get("base_url") and "base_url" not in overrides:
        merged["base_url"] = slot["base_url"]
    if slot.get("api_key") and "api_key" not in overrides:
        merged["api_key"] = slot["api_key"]
    if slot.get("provider_id"):
        merged["provider_id"] = slot["provider_id"]
    if default_model:
        merged["default_model"] = (
            default_model
            if "/" in str(default_model)
            else format_model_ref(slot["provider_id"], slot["model_name"])
            if slot.get("provider_id") and slot.get("model_name")
            else default_model
        )
    elif slot.get("provider_id") and slot.get("model_name"):
        merged["default_model"] = format_model_ref(slot["provider_id"], slot["model_name"])

    env_map = {"api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL", "model_name": "WORKBENCH_AI_MODEL"}
    for key, env_name in env_map.items():
        if merged.get(key):
            os.environ[env_name] = str(merged[key])

    return merged or dict(DEFAULT_RUNTIME_CONFIG)

"""多 LLM 提供商：目录投影、连接/断开、自定义、合成 DeerFlow 单槽。"""
from __future__ import annotations

import re
from typing import Any

from backend.config.credentials import (
    _clean_secret,
    custom_provider,
    load_llm_credentials,
    persist_credentials,
    provider_connection_source,
    resolve_provider_secret,
    resolve_slot,
    stored_provider_key,
)
from backend.config.llm_catalog import (
    LLM_CATALOG,
    POPULAR_PROVIDER_IDS,
    first_model_id,
    format_model_ref,
    get_provider_spec,
    parse_model_ref,
)

_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class LlmProviderError(ValueError):
    pass


class LlmProviderService:
    def __init__(self, *, repo, copilot_service=None) -> None:
        self.repo = repo
        self.copilot_service = copilot_service

    def snapshot(self) -> dict[str, Any]:
        data = load_llm_credentials()
        items = self._all_items(data)
        connected = [item for item in items if item["connected"]]
        connected_ids = {item["id"] for item in connected}
        popular = [
            item for item in items
            if item["id"] in POPULAR_PROVIDER_IDS and item["id"] not in connected_ids
        ]
        popular.sort(key=lambda item: POPULAR_PROVIDER_IDS.index(item["id"]))
        runtime = self._runtime_view(data)
        return {
            "connected": connected,
            "popular": popular,
            "catalog": items,
            "default_model": runtime.get("default_model"),
            "runtime": runtime,
        }

    def connect(self, provider_id: str, api_key: str | None = None) -> dict[str, Any]:
        pid = (provider_id or "").strip()
        spec = get_provider_spec(pid)
        if spec is None:
            data = load_llm_credentials()
            if custom_provider(data, pid) is None:
                raise LlmProviderError(f"未知提供商: {pid}")
            requires_key = True
        else:
            requires_key = spec.requires_key
        key = _clean_secret(api_key)
        if requires_key and not key:
            raise LlmProviderError("请填写 API Key")
        data = load_llm_credentials()
        providers = dict(data.get("providers") or {})
        entry = dict(providers.get(pid) or {})
        if key:
            entry["api_key"] = key
            entry["source"] = "api"
        else:
            entry["source"] = entry.get("source") or "api"
        providers[pid] = entry
        data["providers"] = providers
        if not data.get("default_model"):
            data["default_model"] = self._default_for(pid, spec, data)
        persist_credentials(data)
        self._reconnect()
        return self.snapshot()

    def disconnect(self, provider_id: str) -> dict[str, Any]:
        pid = (provider_id or "").strip()
        data = load_llm_credentials()
        spec = get_provider_spec(pid)
        requires_key = spec.requires_key if spec else True
        source = provider_connection_source(data, pid, requires_key=requires_key)
        if source is None:
            raise LlmProviderError("该提供商尚未连接")
        providers = dict(data.get("providers") or {})
        providers.pop(pid, None)
        data["providers"] = providers
        custom = dict(data.get("custom_providers") or {})
        if pid in custom:
            custom.pop(pid, None)
            data["custom_providers"] = custom
        default = str(data.get("default_model") or "")
        if default.startswith(f"{pid}/"):
            data["default_model"] = self._fallback_default(data, exclude=pid)
        persist_credentials(data)
        self._reconnect()
        return self.snapshot()

    def upsert_custom(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._validate_custom(payload)
        data = load_llm_credentials()
        custom = dict(data.get("custom_providers") or {})
        custom[result["id"]] = result["config"]
        data["custom_providers"] = custom
        providers = dict(data.get("providers") or {})
        entry = dict(providers.get(result["id"]) or {})
        if result.get("api_key"):
            entry["api_key"] = result["api_key"]
            entry["source"] = "api"
        else:
            entry["source"] = entry.get("source") or "custom"
        providers[result["id"]] = entry
        data["providers"] = providers
        if not data.get("default_model"):
            models = result["config"]["models"]
            data["default_model"] = format_model_ref(result["id"], models[0]["id"])
        persist_credentials(data)
        self._reconnect()
        return self.snapshot()

    def assert_connected_model(self, default_model: str) -> None:
        self._assert_connected_model(load_llm_credentials(), default_model)

    def set_default_model(self, default_model: str) -> dict[str, Any]:
        ref = (default_model or "").strip()
        if not ref:
            raise LlmProviderError("default_model 不能为空")
        data = load_llm_credentials()
        provider_id, model_id = self._assert_connected_model(data, ref)
        data["default_model"] = format_model_ref(provider_id, model_id)
        data["model_name"] = model_id
        persist_credentials(data)
        # 档案级覆盖：清掉旧的裸 model_name，避免盖住新的默认
        raw = self.repo.get_config("runtime", {})
        workspace = dict(raw.get("config", raw) or {})
        if workspace.get("model_name") and "/" not in str(workspace.get("model_name")):
            workspace.pop("model_name", None)
            if "config" in raw:
                raw = {**raw, "config": workspace}
                self.repo.set_config("runtime", raw)
            else:
                self.repo.set_config("runtime", workspace)
        self._reconnect()
        return self.snapshot()

    def test_payload(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = dict(payload or {})
        data = load_llm_credentials()
        provider_id = str(extra.get("provider_id") or "").strip() or None
        model_name = extra.get("model_name")
        if provider_id and not extra.get("base_url"):
            spec = get_provider_spec(provider_id)
            custom = custom_provider(data, provider_id)
            extra["base_url"] = spec.base_url if spec else (custom or {}).get("base_url")
            if not extra.get("api_key"):
                extra["api_key"] = resolve_provider_secret(data, provider_id)
            if not model_name:
                extra["model_name"] = first_model_id(spec) if spec else (
                    ((custom or {}).get("models") or [{}])[0].get("id")
                )
            if custom and isinstance(custom.get("headers"), dict):
                extra["headers"] = custom["headers"]
        if not extra.get("api_key") or not extra.get("base_url"):
            slot = resolve_slot(data, str(data.get("default_model") or "") or None)
            extra.setdefault("api_key", slot.get("api_key"))
            extra.setdefault("base_url", slot.get("base_url"))
            extra.setdefault("model_name", slot.get("model_name"))
            extra.setdefault("headers", slot.get("headers") or {})
        return extra

    def _reconnect(self) -> None:
        if self.copilot_service is not None:
            self.copilot_service.reconnect_runtime()

    def _runtime_view(self, data: dict[str, Any]) -> dict[str, Any]:
        from backend.config.credentials import effective_runtime_config

        merged = effective_runtime_config(self.repo)
        default_model = merged.get("default_model") or data.get("default_model")
        provider_id, model_id = parse_model_ref(str(default_model) if default_model else None)
        if provider_id is None:
            slot = resolve_slot(data, str(default_model) if default_model else None)
            provider_id = slot.get("provider_id")
            model_id = slot.get("model_name")
            if provider_id and model_id:
                default_model = format_model_ref(provider_id, model_id)
        spec = get_provider_spec(provider_id) if provider_id else None
        custom = custom_provider(data, provider_id) if provider_id else None
        name = spec.name if spec else (custom or {}).get("name")
        source = None
        if provider_id:
            source = provider_connection_source(
                data, provider_id, requires_key=spec.requires_key if spec else True
            )
        deerflow = None
        if self.copilot_service is not None:
            deerflow = self.copilot_service.deerflow.status().to_dict()
        return {
            "default_model": default_model,
            "provider_id": provider_id,
            "provider_name": name,
            "model_id": model_id,
            "source": source,
            "connected": bool(provider_id and source),
            "agent_runtime": deerflow,
        }

    def _all_items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for spec in LLM_CATALOG:
            source = provider_connection_source(data, spec.id, requires_key=spec.requires_key)
            items.append({
                "id": spec.id,
                "name": spec.name,
                "base_url": spec.base_url,
                "popular": spec.popular,
                "requires_key": spec.requires_key,
                "note": spec.note,
                "models": [{"id": m.id, "name": m.name} for m in spec.models],
                "connected": source is not None,
                "source": source,
                "can_disconnect": source is not None,
                "has_key": bool(resolve_provider_secret(data, spec.id)),
                "custom": False,
            })
            seen.add(spec.id)
        for pid, meta in (data.get("custom_providers") or {}).items():
            if not isinstance(meta, dict):
                continue
            pid = str(pid)
            models = [
                {"id": str(m.get("id")), "name": str(m.get("name") or m.get("id"))}
                for m in (meta.get("models") or [])
                if isinstance(m, dict) and m.get("id")
            ]
            source = provider_connection_source(data, pid, requires_key=True)
            if source is None and stored_provider_key(data, pid):
                source = "custom"
            if source is None and models:
                # 已保存自定义配置即视为已连接（Key 可能稍后补）
                source = "custom" if stored_provider_key(data, pid) else None
            if stored_provider_key(data, pid) and source is None:
                source = "custom"
            connected = source is not None
            items.append({
                "id": pid,
                "name": str(meta.get("name") or pid),
                "base_url": str(meta.get("base_url") or ""),
                "popular": False,
                "requires_key": True,
                "note": None,
                "models": models,
                "connected": connected,
                "source": source,
                "can_disconnect": connected,
                "has_key": bool(stored_provider_key(data, pid)),
                "custom": True,
            })
            seen.add(pid)
        return items

    def _assert_connected_model(
        self, data: dict[str, Any], default_model: str
    ) -> tuple[str, str]:
        ref = (default_model or "").strip()
        provider_id, model_id = parse_model_ref(ref)
        if provider_id is None or not model_id:
            raise LlmProviderError("default_model 需为 provider_id/model_id")
        item = next((row for row in self._all_items(data) if row["id"] == provider_id), None)
        if item is None or not item["connected"]:
            raise LlmProviderError("只能选择已连接提供商下的模型")
        model_ids = {m["id"] for m in item["models"]}
        if model_id not in model_ids:
            raise LlmProviderError(f"模型不在 {provider_id} 的目录中")
        return provider_id, model_id

    def _default_for(self, pid: str, spec, data: dict[str, Any]) -> str:
        if spec is not None:
            return format_model_ref(pid, first_model_id(spec))
        custom = custom_provider(data, pid) or {}
        models = custom.get("models") or []
        model_id = models[0]["id"] if models and isinstance(models[0], dict) else pid
        return format_model_ref(pid, str(model_id))

    def _fallback_default(self, data: dict[str, Any], *, exclude: str) -> str | None:
        for item in self._all_items(data):
            if item["id"] == exclude or not item["connected"]:
                continue
            models = item.get("models") or []
            if not models:
                continue
            return format_model_ref(item["id"], models[0]["id"])
        return None

    def _validate_custom(self, payload: dict[str, Any]) -> dict[str, Any]:
        pid = str(payload.get("id") or "").strip().lower()
        name = str(payload.get("name") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        if not _PROVIDER_ID_RE.match(pid):
            raise LlmProviderError("提供商 ID 需为小写字母开头的字母数字、下划线或短横线")
        if get_provider_spec(pid):
            raise LlmProviderError("不能覆盖内置提供商 ID，请换一个 ID")
        if not name:
            raise LlmProviderError("请填写显示名称")
        if not base_url:
            raise LlmProviderError("请填写 Base URL")
        models_in = payload.get("models") or []
        models: list[dict[str, str]] = []
        seen: set[str] = set()
        if not isinstance(models_in, list):
            raise LlmProviderError("models 必须是列表")
        for row in models_in:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("id") or "").strip()
            mname = str(row.get("name") or mid).strip()
            if not mid:
                continue
            if mid in seen:
                raise LlmProviderError(f"重复的模型 ID: {mid}")
            seen.add(mid)
            models.append({"id": mid, "name": mname or mid})
        if not models:
            raise LlmProviderError("至少添加一个模型")
        headers_in = payload.get("headers") or {}
        headers: dict[str, str] = {}
        if isinstance(headers_in, dict):
            for key, value in headers_in.items():
                k = str(key).strip()
                if not k or value is None or str(value) == "":
                    continue
                headers[k] = str(value)
        elif isinstance(headers_in, list):
            for row in headers_in:
                if not isinstance(row, dict):
                    continue
                k = str(row.get("key") or "").strip()
                v = row.get("value")
                if k and v not in (None, ""):
                    headers[k] = str(v)
        api_key = _clean_secret(payload.get("api_key"))
        return {
            "id": pid,
            "api_key": api_key,
            "config": {
                "name": name,
                "base_url": base_url,
                "models": models,
                "headers": headers,
            },
        }

"""内置 LLM 提供商目录（OpenAI-compatible）。

DeerFlow 只吃一组 OPENAI_API_KEY / OPENAI_BASE_URL / WORKBENCH_AI_MODEL，
因此目录里每家都必须带 base_url 与模型 id；Anthropic/Gemini 原生协议不收录，
走自定义兼容网关。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class LlmModelSpec:
    id: str
    name: str


@dataclass(frozen=True)
class LlmProviderSpec:
    id: str
    name: str
    base_url: str
    models: tuple[LlmModelSpec, ...]
    popular: bool = False
    requires_key: bool = True
    note: str | None = None


LLM_CATALOG: tuple[LlmProviderSpec, ...] = (
    LlmProviderSpec(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        popular=True,
        models=(
            LlmModelSpec("deepseek-v4-flash", "DeepSeek V4 Flash"),
            LlmModelSpec("deepseek-v4-pro", "DeepSeek V4 Pro"),
            LlmModelSpec("deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision"),
        ),
    ),
    LlmProviderSpec(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        popular=True,
        note="官方 API。第三方兼容网关请用自定义提供商。",
        models=(
            LlmModelSpec("gpt-5.4", "GPT-5.4"),
            LlmModelSpec("gpt-4.1", "GPT-4.1"),
            LlmModelSpec("gpt-4o", "GPT-4o"),
        ),
    ),
    LlmProviderSpec(
        id="kimi",
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        popular=True,
        note="月之暗面 Kimi 官方 API（中国大陆）。",
        models=(
            LlmModelSpec("kimi-k2.6", "Kimi K2.6"),
            LlmModelSpec("kimi-k3", "Kimi K3"),
            LlmModelSpec("kimi-k2.5", "Kimi K2.5"),
        ),
    ),
    LlmProviderSpec(
        id="qwen",
        name="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        popular=True,
        note="阿里云百炼 DashScope OpenAI 兼容接口。",
        models=(
            LlmModelSpec("qwen3.8-max", "Qwen3.8 Max"),
            LlmModelSpec("qwen3.7-plus", "Qwen3.7 Plus"),
            LlmModelSpec("qwen3.7-flash", "Qwen3.7 Flash"),
        ),
    ),
    LlmProviderSpec(
        id="zhipu",
        name="智谱",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        popular=True,
        note="智谱 GLM 官方 OpenAI 兼容接口。",
        models=(
            LlmModelSpec("glm-5.3", "GLM-5.3"),
            LlmModelSpec("glm-5.3-flash", "GLM-5.3 Flash"),
            LlmModelSpec("glm-5.2", "GLM-5.2"),
        ),
    ),
    LlmProviderSpec(
        id="mimo",
        name="MiMo",
        base_url="https://api.xiaomimimo.com/v1",
        popular=True,
        note="小米 MiMo 官方 API。Token Plan 用户请在自定义提供商里填写专属 Base URL。",
        models=(
            LlmModelSpec("mimo-v2.5-pro", "MiMo V2.5 Pro"),
            LlmModelSpec("mimo-v2.5", "MiMo V2.5"),
        ),
    ),
    LlmProviderSpec(
        id="siliconflow",
        name="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        popular=True,
        models=(
            LlmModelSpec("deepseek-ai/DeepSeek-V3", "DeepSeek V3"),
            LlmModelSpec("Qwen/Qwen2.5-72B-Instruct", "Qwen2.5 72B"),
        ),
    ),
    LlmProviderSpec(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        popular=True,
        models=(
            LlmModelSpec("openai/gpt-4o", "GPT-4o"),
            LlmModelSpec("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6"),
            LlmModelSpec("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash"),
        ),
    ),
    LlmProviderSpec(
        id="ollama",
        name="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        popular=True,
        requires_key=False,
        note="本地 OpenAI 兼容接口，通常无需 Key。",
        models=(
            LlmModelSpec("llama3.1", "Llama 3.1"),
            LlmModelSpec("qwen2.5", "Qwen 2.5"),
        ),
    ),
)

LLM_CATALOG_BY_ID: dict[str, LlmProviderSpec] = {item.id: item for item in LLM_CATALOG}
POPULAR_PROVIDER_IDS: tuple[str, ...] = tuple(item.id for item in LLM_CATALOG if item.popular)


_LEGACY_PROVIDER_ID = "legacy"


def catalog_as_dicts() -> list[dict[str, Any]]:
    return [_spec_to_dict(item) for item in LLM_CATALOG]


def get_provider_spec(provider_id: str) -> LlmProviderSpec | None:
    return LLM_CATALOG_BY_ID.get(provider_id)


def parse_model_ref(value: str | None) -> tuple[str | None, str | None]:
    raw = (value or "").strip()
    if not raw:
        return None, None
    if "/" not in raw:
        return None, raw
    provider_id, model_id = raw.split("/", 1)
    provider_id = provider_id.strip()
    model_id = model_id.strip()
    if not provider_id or not model_id:
        return None, raw
    return provider_id, model_id


def format_model_ref(provider_id: str, model_id: str) -> str:
    return f"{provider_id}/{model_id}"


def first_model_id(spec: LlmProviderSpec) -> str:
    return spec.models[0].id if spec.models else spec.id


def match_provider_by_base_url(base_url: str | None) -> str | None:
    host = _host(base_url)
    if not host:
        return None
    for spec in LLM_CATALOG:
        if _host(spec.base_url) == host:
            return spec.id
    return None


def _host(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.netloc or "").lower().removeprefix("www.")


def _spec_to_dict(spec: LlmProviderSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "base_url": spec.base_url,
        "popular": spec.popular,
        "requires_key": spec.requires_key,
        "note": spec.note,
        "models": [{"id": m.id, "name": m.name} for m in spec.models],
    }

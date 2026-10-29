"""内置 LLM 提供商目录（OpenAI-compatible）。

**更新于 2026-10-29**，依据：
- DeepSeek 官方 changelog（2026-10-17，deepseek-flash = V4.1 Flash）
- Kimi / 智谱 官方模型与定价页
- OpenRouter 公开 `GET /api/v1/models`（各家当前 id 与上下文长度）
- SiliconFlow 模型广场（平台在售 id）
- Ollama 库页热门榜

各家迭代很快，这份目录是**默认候选**而不是白名单：自定义提供商里可以填任何 id。


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
        note="官方 changelog 2026-10-17：deepseek-flash 即 V4.1 Flash（原生多模态）。"
             "旧名 deepseek-v4-flash / deepseek-v4-flash-vision-exp 会临时路由到 V4.1 Flash。",
        models=(
            LlmModelSpec("deepseek-flash", "DeepSeek V4.1 Flash"),
            LlmModelSpec("deepseek-v4-pro", "DeepSeek V4 Pro"),
            LlmModelSpec("deepseek-v4-flash", "V4 Flash（旧名，路由到 V4.1）"),
        ),
    ),
    LlmProviderSpec(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        popular=True,
        note="官方 API。第三方兼容网关请用自定义提供商。",
        models=(
            LlmModelSpec("gpt-6.1-terra-pro", "GPT-6.1 Terra Pro"),
            LlmModelSpec("gpt-6.1-terra", "GPT-6.1 Terra"),
            LlmModelSpec("gpt-6.1-sol-pro", "GPT-6.1 Sol Pro"),
            LlmModelSpec("gpt-6.1-sol", "GPT-6.1 Sol"),
            LlmModelSpec("gpt-6-luna", "GPT-6 Luna"),
        ),
    ),
    LlmProviderSpec(
        id="kimi",
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        popular=True,
        note="月之暗面 Kimi 官方 API（中国大陆）。K3 系列 1M 上下文；"
             "K2 系列将于 2026 年底退役。",
        models=(
            LlmModelSpec("kimi-k3.1-pro", "Kimi K3.1 Pro"),
            LlmModelSpec("kimi-k3", "Kimi K3"),
            LlmModelSpec("kimi-k2.7-code", "Kimi K2.7 Code"),
            LlmModelSpec("kimi-k2.6", "Kimi K2.6"),
        ),
    ),
    LlmProviderSpec(
        id="qwen",
        name="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        popular=True,
        note="阿里云百炼 DashScope OpenAI 兼容接口。具体可用的快照 id 以控制台为准。",
        models=(
            LlmModelSpec("qwen3.8-max", "Qwen3.8 Max"),
            LlmModelSpec("qwen3.8-max-0902", "Qwen3.8 Max（0902 快照）"),
            LlmModelSpec("qwen3.8-flash", "Qwen3.8 Flash"),
            LlmModelSpec("qwen3.8-omni-flash", "Qwen3.8 Omni Flash"),
        ),
    ),
    LlmProviderSpec(
        id="zhipu",
        name="智谱",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        popular=True,
        note="智谱 GLM 官方 OpenAI 兼容接口。GLM-5.3 固定开启思考，"
             "推理强度 low/high/max。",
        models=(
            LlmModelSpec("glm-5.3", "GLM-5.3"),
            LlmModelSpec("glm-5.3-flash", "GLM-5.3 Flash"),
            LlmModelSpec("glm-5.3-flashx", "GLM-5.3 FlashX"),
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
            LlmModelSpec("mimo-v2.6-pro", "MiMo V2.6 Pro"),
            LlmModelSpec("mimo-v2.6-flash", "MiMo V2.6 Flash"),
            LlmModelSpec("mimo-v2.5-pro", "MiMo V2.5 Pro"),
        ),
    ),
    LlmProviderSpec(
        id="siliconflow",
        name="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        popular=True,
        models=(
            LlmModelSpec("deepseek-ai/DeepSeek-V4.1-Flash", "DeepSeek V4.1 Flash"),
            LlmModelSpec("deepseek-ai/DeepSeek-V4-Pro", "DeepSeek V4 Pro"),
            LlmModelSpec("moonshotai/Kimi-K3", "Kimi K3"),
            LlmModelSpec("zai-org/GLM-5.3", "GLM-5.3"),
            LlmModelSpec("Qwen/Qwen3.8-27B", "Qwen3.8 27B"),
        ),
    ),
    LlmProviderSpec(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        popular=True,
        models=(
            LlmModelSpec("openai/gpt-6.1-terra", "GPT-6.1 Terra"),
            LlmModelSpec("anthropic/claude-opus-5.5", "Claude Opus 5.5"),
            LlmModelSpec("google/gemini-4-argon", "Gemini 4 Argon"),
            LlmModelSpec("moonshotai/kimi-k3.1-pro", "Kimi K3.1 Pro"),
            LlmModelSpec("deepseek/deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash"),
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
            LlmModelSpec("qwen3.5", "Qwen 3.5"),
            LlmModelSpec("gemma4", "Gemma 4"),
            LlmModelSpec("qwen3", "Qwen 3"),
            LlmModelSpec("deepseek-r1", "DeepSeek R1"),
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

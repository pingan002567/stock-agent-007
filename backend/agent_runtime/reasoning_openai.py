"""保留思维链的 ChatOpenAI 变体（适配所有 OpenAI 兼容网关）。

背景：`langchain_openai.ChatOpenAI` 只处理官方 OpenAI 规范，
第三方网关多出来的 `reasoning_content` / `reasoning` / `reasoning_details`
在**解析阶段**就被丢掉（官方注释写得很明确）。而我们的 DeepSeek / Kimi /
Qwen / GLM / MiMo / SiliconFlow / OpenRouter 全都是 OpenAI 兼容网关，
思维链字段名各不相同：

- DeepSeek、Kimi、Qwen、GLM、MiMo、SiliconFlow：``reasoning_content``
- OpenRouter：``reasoning``（有时还有 ``reasoning_details``）
- 官方 OpenAI Responses：``reasoning``

这个类做三件事：
1. **流式**：把 delta 里的思维链字段塞进 ``additional_kwargs``，下游才能取到；
2. **非流式**：同样从原始 response 里捞出来；
3. **多轮回放**：把 assistant 消息的 ``reasoning_content`` 原样带回请求体 ——
   DeepSeek/GLM 这类思考模式下缺了它会直接 400。

不使用子类覆盖 ``_convert_delta_to_message_chunk``：它是 langchain_openai
的模块级函数，拿不到；改为覆盖 ``_convert_chunk_to_generation_chunk``，
先让父类正常转换，再补字段，对上游版本变化更稳。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

#: 各家网关的思维链字段名（按优先级）
REASONING_FIELDS = ("reasoning_content", "reasoning", "reasoning_details")


def reasoning_text_of(value: Any) -> str:
    """把任意形状的思维链字段拍成文本（str / dict / list 都见过）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [reasoning_text_of(item) for item in value]
        return "".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "reasoning", "summary", "thinking"):
            if key in value:
                text = reasoning_text_of(value[key])
                if text:
                    return text
        return ""
    return str(value).strip()


def extract_reasoning(source: Any) -> dict[str, Any]:
    """从 delta / message 字典里抽出思维链，返回要并入 additional_kwargs 的字段。"""
    if not isinstance(source, dict):
        return {}
    out: dict[str, Any] = {}
    for field in REASONING_FIELDS:
        value = source.get(field)
        if value in (None, "", [], {}):
            continue
        out[field] = value
        text = reasoning_text_of(value)
        if text:
            # 统一再放一份文本版，下游只认 reasoning_content 也能用
            out["reasoning_content"] = text
            break
    return out


class ReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI + 思维链保真。"""

    @property
    def _llm_type(self) -> str:
        return "openai-compatible-reasoning"

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        choices = chunk.get("choices") or []
        if not choices:
            return generation_chunk
        delta = choices[0].get("delta") or {}
        reasoning = extract_reasoning(delta)
        message = generation_chunk.message
        if reasoning and isinstance(message, AIMessage):
            message.additional_kwargs.update(reasoning)
        return generation_chunk

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ):
        result = super()._create_chat_result(response, generation_info=generation_info)
        try:
            response_dict = response if isinstance(response, dict) else response.model_dump()
        except Exception:  # noqa: BLE001 - 拿不到原始响应就不补字段
            return result
        for generation, choice in zip(result.generations, response_dict.get("choices") or []):
            message = getattr(generation, "message", None)
            if not isinstance(message, AIMessage):
                continue
            reasoning = extract_reasoning((choice or {}).get("message") or {})
            if reasoning:
                message.additional_kwargs.update(reasoning)
        return result

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        original = self._convert_input(input_).to_messages()
        payload_messages = payload.get("messages") or []
        assistant_payloads = [m for m in payload_messages if m.get("role") == "assistant"]
        ai_messages = [m for m in original if isinstance(m, AIMessage)]
        for payload_msg, ai_msg in zip(assistant_payloads, ai_messages):
            extra = ai_msg.additional_kwargs or {}
            text = reasoning_text_of(extra.get("reasoning_content") or extra.get("reasoning"))
            if text:
                # 思考模式要求 assistant 消息带上 reasoning_content，缺了会 400
                payload_msg["reasoning_content"] = text
        return payload

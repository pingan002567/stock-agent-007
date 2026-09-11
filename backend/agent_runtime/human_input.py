"""DeerFlow-aligned human_input request/response helpers.

Official DeerFlow (upstream) emits ToolMessage.artifact.human_input and accepts
HumanMessage.additional_kwargs.human_input_response. Installed harness 2.1 still
formats ask_clarification as markdown only; we rebuild the native request shape
from tool-call args so the workbench UI can match Human Input Card without a
parallel clarification middleware.
"""

from __future__ import annotations

import re
from typing import Any

# Harness formats options as "1. …" / "  2) …" lines inside the tool result markdown.
_NUMBERED_OPTION_RE = re.compile(
    r"^\s*(?:\d+[\.\、\)]\s+|[-*]\s+)(.+?)\s*$",
    re.MULTILINE,
)
_CONTEXT_EMOJI_RE = re.compile(r"^[🧩❓ℹ️]\s*")


def _non_empty_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalize_options(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [raw]
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            label = _non_empty_str(item.get("label") or item.get("value") or item.get("id"))
            value = _non_empty_str(item.get("value") or item.get("label") or item.get("id"))
            option_id = _non_empty_str(item.get("id")) or f"opt-{idx}"
        else:
            label = _non_empty_str(item)
            value = label
            option_id = f"opt-{idx}"
        if not label or not value or option_id in seen or value in {o["value"] for o in options}:
            continue
        seen.add(option_id)
        options.append({"id": option_id, "label": label, "value": value})
    return options


def extract_options_from_markdown(text: str | None) -> list[dict[str, str]]:
    """Pull numbered / bulleted choices out of harness markdown result text."""
    if not text:
        return []
    labels: list[str] = []
    for match in _NUMBERED_OPTION_RE.finditer(text):
        label = match.group(1).strip()
        if label:
            labels.append(label)
    return _normalize_options(labels)


def split_clarification_markdown(text: str | None) -> tuple[str | None, str, list[dict[str, str]]]:
    """Split harness markdown into (context, question, options).

    Typical shape::
        🧩 context paragraph…

        第 1 个问题：question text…
        1. option A
        2. option B
    """
    raw = (text or "").strip()
    if not raw:
        return None, "需要你补充一些信息才能继续", []

    options = extract_options_from_markdown(raw)
    body = raw
    if options:
        # Drop trailing numbered list so question/context stay clean.
        lines = raw.splitlines()
        kept: list[str] = []
        for line in lines:
            if _NUMBERED_OPTION_RE.match(line):
                break
            kept.append(line)
        body = "\n".join(kept).strip()

    body = _CONTEXT_EMOJI_RE.sub("", body).strip()
    context: str | None = None
    question = body or raw

    # Prefer an explicit "第 N 个问题：" split when present.
    q_match = re.search(r"(第\s*\d+\s*个问题[:：]\s*)", body)
    if q_match:
        before = body[: q_match.start()].strip()
        after = body[q_match.end() :].strip()
        if before:
            context = before
        if after:
            question = after
    else:
        parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if len(parts) >= 2:
            context = parts[0]
            question = "\n\n".join(parts[1:])

    question = re.sub(r"^第\s*\d+\s*个问题[:：]\s*", "", question).strip() or question
    return context, question, options


def extract_human_input_from_tool_result(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prefer DeerFlow-native ToolMessage.artifact.human_input when present."""
    if not isinstance(payload, dict):
        return None
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        human_input = artifact.get("human_input")
        if isinstance(human_input, dict) and human_input.get("kind") == "human_input_request":
            # Keep legacy aliases used by older UI/SSE consumers.
            out = dict(human_input)
            call_id = out.get("tool_call_id") or payload.get("call_id")
            if call_id and "call_id" not in out:
                out["call_id"] = call_id
            if call_id and "tool_call_id" not in out:
                out["tool_call_id"] = call_id
            return out
    return None


def build_human_input_request(
    *,
    args: dict[str, Any] | None,
    call_id: str | None,
    formatted_result: str | None = None,
) -> dict[str, Any]:
    """Build a DeerFlow-native human_input_request from ask_clarification args."""
    args = dict(args or {})
    md_context, md_question, md_options = split_clarification_markdown(formatted_result)
    question = (
        _non_empty_str(args.get("question"))
        or _non_empty_str(md_question)
        or "需要你补充一些信息才能继续"
    )
    # If the model stuffed the whole markdown blob into `question`, re-split it.
    if "\n" in question and (
        extract_options_from_markdown(question) or re.search(r"第\s*\d+\s*个问题", question)
    ):
        split_ctx, split_q, split_opts = split_clarification_markdown(question)
        question = split_q or question
        if not md_context:
            md_context = split_ctx
        if not md_options:
            md_options = split_opts

    call = _non_empty_str(call_id) or "unknown"
    request_id = f"clarification:{call}"
    options = _normalize_options(args.get("options")) or md_options
    raw_fields = args.get("fields")
    fields: list[dict[str, Any]] = []
    if isinstance(raw_fields, list):
        for entry in raw_fields:
            if not isinstance(entry, dict):
                continue
            name = _non_empty_str(entry.get("name"))
            label = _non_empty_str(entry.get("label")) or name
            if not name or not label:
                continue
            field_type = str(entry.get("type") or "text")
            fields.append(
                {
                    "name": name,
                    "label": label,
                    "type": field_type,
                    "required": bool(entry.get("required")),
                    **(
                        {"placeholder": str(entry["placeholder"])}
                        if entry.get("placeholder") is not None
                        else {}
                    ),
                    **(
                        {"options": _normalize_options(entry.get("options"))}
                        if entry.get("options") is not None
                        else {}
                    ),
                }
            )

    if fields:
        version, input_mode = 2, "form"
    elif options:
        version, input_mode = 1, "choice_with_other"
    else:
        version, input_mode = 1, "free_text"

    payload: dict[str, Any] = {
        "version": version,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": request_id,
        "tool_call_id": call,
        "question": question,
        "input_mode": input_mode,
    }
    clarification_type = _non_empty_str(args.get("clarification_type"))
    if clarification_type:
        payload["clarification_type"] = clarification_type
    context = args.get("context")
    if context is None or isinstance(context, str):
        if _non_empty_str(context):
            payload["context"] = str(context).strip()
        elif md_context:
            payload["context"] = md_context
        else:
            payload["context"] = None
    if input_mode == "form":
        payload["fields"] = fields
    elif options:
        payload["options"] = options
    # Keep legacy aliases for existing SSE consumers / activity summary.
    payload["call_id"] = call
    return payload


def normalize_human_input_response(raw: Any) -> dict[str, Any] | None:
    """Validate outbound human_input_response metadata (DeerFlow-native v1)."""
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != 1 or raw.get("kind") != "human_input_response":
        return None
    source = _non_empty_str(raw.get("source")) or "ask_clarification"
    request_id = _non_empty_str(raw.get("request_id"))
    value = _non_empty_str(raw.get("value"))
    if not request_id or not value:
        return None
    response_kind = raw.get("response_kind")
    if response_kind == "text":
        return {
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": request_id,
            "response_kind": "text",
            "value": value,
        }
    if response_kind == "option":
        option_id = _non_empty_str(raw.get("option_id"))
        if not option_id:
            return None
        return {
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": request_id,
            "response_kind": "option",
            "option_id": option_id,
            "value": value,
        }
    return None


def build_response_message_text(question: str, value: str) -> str:
    """Readable bridge text (matches DeerFlow frontend template intent)."""
    q = question.strip() or "your clarification"
    return f'For your clarification "{q}", my answer is: {value.strip()}'

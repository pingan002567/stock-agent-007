from backend.agent_runtime.human_input import (
    build_human_input_request,
    build_response_message_text,
    normalize_human_input_response,
)


def test_build_human_input_request_free_text():
    payload = build_human_input_request(
        args={"question": "持仓比例？", "clarification_type": "missing_info"},
        call_id="c1",
    )
    assert payload["kind"] == "human_input_request"
    assert payload["input_mode"] == "free_text"
    assert payload["request_id"] == "clarification:c1"
    assert payload["question"] == "持仓比例？"
    assert "options" not in payload


def test_build_human_input_request_choice_with_other():
    payload = build_human_input_request(
        args={
            "question": "选哪只？",
            "options": ["茅台", "五粮液"],
        },
        call_id="c2",
        formatted_result="fallback",
    )
    assert payload["input_mode"] == "choice_with_other"
    assert [o["value"] for o in payload["options"]] == ["茅台", "五粮液"]


def test_build_human_input_request_parses_markdown_options():
    formatted = (
        "🧩 A股板块口径很宽，范围决定了后续分析的落点。\n\n"
        "第 1 个问题：这次分析范围是哪一种？\n"
        "1. 全市场轮动\n"
        "2. 持仓相关\n"
        "3. 事件驱动"
    )
    payload = build_human_input_request(
        args={"question": "这次分析范围是哪一种？"},
        call_id="c3",
        formatted_result=formatted,
    )
    assert payload["input_mode"] == "choice_with_other"
    assert [o["label"] for o in payload["options"]] == ["全市场轮动", "持仓相关", "事件驱动"]
    assert payload["context"] and "板块口径" in payload["context"]
    assert "1." not in payload["question"]


def test_normalize_human_input_response():
    ok = normalize_human_input_response(
        {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "clarification:c1",
            "response_kind": "option",
            "option_id": "opt-1",
            "value": "茅台",
        }
    )
    assert ok and ok["response_kind"] == "option"
    assert normalize_human_input_response({"kind": "nope"}) is None


def test_extract_human_input_from_tool_result_prefers_artifact():
    from backend.agent_runtime.human_input import extract_human_input_from_tool_result

    payload = extract_human_input_from_tool_result(
        {
            "call_id": "c9",
            "tool": "ask_clarification",
            "result": "fallback text",
            "artifact": {
                "human_input": {
                    "version": 2,
                    "kind": "human_input_request",
                    "source": "ask_clarification",
                    "request_id": "clarification:c9",
                    "question": "填一下参数",
                    "input_mode": "form",
                    "fields": [{"name": "n", "label": "N", "type": "number", "required": True}],
                }
            },
        }
    )
    assert payload and payload["input_mode"] == "form"
    assert payload["call_id"] == "c9"


def test_build_response_message_text():
    text = build_response_message_text("选哪只？", "茅台")
    assert "选哪只？" in text and "茅台" in text

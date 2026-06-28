from __future__ import annotations

import asyncio
import json
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from backend.schemas import AuthorityLevel, HoldingPosition, ReportGenerateRequest


def make_client(tmp_path) -> TestClient:
    from backend.app import create_app

    app = create_app(db_path=tmp_path / "copilot.sqlite3", files_root=tmp_path / "files")
    return TestClient(app)


def parse_sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for chunk in body.split("\n\n"):
        if not chunk.startswith("event: "):
            continue
        data_line = [line for line in chunk.splitlines() if line.startswith("data: ")][0]
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


class _SmokeHtmlParser(HTMLParser):
    pass


def test_copilot_session_message_history_and_persisted_stream_recovery(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/copilot/sessions",
        json={
            "title": "AAPL 风险复核",
            "current_page": "stock",
            "anchor_symbol": "AAPL",
            "authority_level": "A4",
        },
    )
    assert created.status_code == 200
    session = created.json()
    assert session["current_page"] == "stock"
    assert session["anchor_symbol"] == "AAPL"

    started = client.post(
        f"/api/copilot/sessions/{session['session_id']}/messages",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "client_message_id": "client-msg-001",
        },
    )
    assert started.status_code == 200
    run = started.json()
    assert run["session_id"] == session["session_id"]
    assert run["message_id"]
    assert run["task_id"]
    assert run["run_id"]

    client.app.state.services.copilot_service._runs.clear()

    with client.stream("GET", f"/api/copilot/sessions/{session['session_id']}/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert events[0]["type"] == "skill_trace"
    assert events[-1]["type"] == "final"
    assert all(event["run_id"] == run["run_id"] for event in events)
    assert all(event["task_id"] == run["task_id"] for event in events)

    detail = client.get(f"/api/copilot/sessions/{session['session_id']}")
    assert detail.status_code == 200
    assert detail.json()["last_message_at"]

    messages = client.get(f"/api/copilot/sessions/{session['session_id']}/messages")
    assert messages.status_code == 200
    items = messages.json()["items"]
    assert [item["role"] for item in items[:2]] == ["user", "system"]
    assert {item["kind"] for item in items} >= {"user_message", "skill_trace", "final_answer"}
    assert any(item["run_id"] == run["run_id"] and item["task_id"] == run["task_id"] for item in items)
    assert any(item["client_message_id"] == "client-msg-001" for item in items)


def test_legacy_copilot_chat_remains_compatible_and_returns_session_fields(tmp_path):
    client = make_client(tmp_path)

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
            "client_message_id": "legacy-msg-001",
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["session_id"]
    assert payload["message_id"]
    assert payload["run_id"]
    assert payload["task_id"]
    assert payload["skills"]

    with client.stream("GET", f"/api/copilot/stream/{payload['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    events = parse_sse_events(body)
    assert events[-1]["type"] == "final"

    history = client.get(f"/api/copilot/sessions/{payload['session_id']}/messages")
    assert history.status_code == 200
    assert any(item["message_id"] == payload["message_id"] for item in history.json()["items"])


def test_missing_copilot_stream_returns_404_instead_of_fake_continue(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/copilot/stream/run_missing_404")

    assert response.status_code == 404
    assert "not found" in response.text.lower()


def test_partial_stream_recovery_replays_without_rerunning_side_effect_tools(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "把 AAPL 降到 15% 并生成调仓方案",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    async def consume_until_tool_result():
        seen = []
        agen = services.copilot_service.stream_run(run["run_id"], run["task_id"])
        try:
            async for event in agen:
                seen.append(event)
                if event.type == "tool_result":
                    break
        finally:
            await agen.aclose()
        return seen

    partial_events = asyncio.run(consume_until_tool_result())
    assert any(event.type == "tool_result" for event in partial_events)
    drafts_before = client.get("/api/rebalance-drafts").json()["items"]
    assert len(drafts_before) == 1

    services.copilot_service._runs.clear()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events][-2:] == ["error", "final"]
    assert events[-2]["payload"]["stage"] == "stream_recovery"
    assert "避免重复创建" in events[-1]["payload"]["conclusion"]
    drafts_after = client.get("/api/rebalance-drafts").json()["items"]
    assert [item["draft_id"] for item in drafts_after] == [item["draft_id"] for item in drafts_before]


def test_copilot_context_builder_redacts_full_holdings_reports_and_tool_args(tmp_path):
    from backend.bootstrap import create_services

    services = create_services(db_path=tmp_path / "context.sqlite3", files_root=tmp_path / "files")
    services.repo.upsert_holding(
        HoldingPosition(
            symbol="MSFT",
            name="Microsoft",
            quantity=999,
            market_value=401234,
            weight_pct=9.1,
            cost=123.45,
            pnl_pct=25.6,
        )
    )
    report = services.report_service.generate(
        ReportGenerateRequest(
            report_type="stock_research",
            source_type="stock",
            source_id="AAPL",
        )
    )
    secret_marker = "super-secret-tool-argument"
    task = services.task_service.create("Secret task", "risk-officer", "testing")
    services.tool_execution_service.record(
        tool="evaluate_policy_risk",
        domain="risk",
        status="succeeded",
        authority_level=AuthorityLevel.A3.value,
        arguments={"token": secret_marker},
        task_id=task.task_id,
        run_id="run_context_redaction",
        result={"secret": secret_marker},
    )

    payload = services.copilot_context_builder.build(page="holdings", symbol="AAPL")
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "super-secret-tool-argument" not in serialized
    assert report.content not in serialized
    assert "markdown_path" not in serialized
    assert "quantity\": 999" not in serialized
    assert "cost\": 123.45" not in serialized


def test_execution_policy_allows_only_low_risk_automatic_actions():
    from backend.app_services.execution_policy import ExecutionMode, ExecutionPolicy

    policy = ExecutionPolicy(default_mode=ExecutionMode.AUTO_SAFE)

    assert policy.decide("evaluate_policy_risk").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("analyze_portfolio_risk").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("run_strategy_backtest").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("generate_report").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("evaluate_monitor_rules").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("create_paper_portfolio_snapshot").mode is ExecutionMode.AUTO_SAFE

    assert policy.decide("generate_draft_order").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("create_pre_trade_review").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("draft_confirm").mode is ExecutionMode.NEEDS_CONFIRMATION
    assert policy.decide("draft_reject").mode is ExecutionMode.NEEDS_CONFIRMATION
    assert policy.decide("create_paper_order").mode is ExecutionMode.NEEDS_CONFIRMATION
    assert policy.decide("cancel_paper_order").mode is ExecutionMode.NEEDS_CONFIRMATION
    assert policy.decide("decision_journal_close").mode is ExecutionMode.NEEDS_CONFIRMATION
    assert policy.decide("decision_journal_link_snapshot").mode is ExecutionMode.NEEDS_CONFIRMATION
    # Review-inbox actions are deliberately low-risk auto-safe (with audit); the real
    # tool names are dismiss_inbox_item / snooze_inbox_item / mark_inbox_item_done.
    assert policy.decide("dismiss_inbox_item").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("snooze_inbox_item").mode is ExecutionMode.AUTO_SAFE
    assert policy.decide("mark_inbox_item_done").mode is ExecutionMode.AUTO_SAFE

    assert policy.decide("place_real_order").mode is ExecutionMode.BLOCKED
    assert policy.decide("TeamRun").mode is ExecutionMode.BLOCKED


def test_execution_policy_unknown_action_uses_default_mode():
    from backend.app_services.execution_policy import ExecutionMode, ExecutionPolicy

    policy = ExecutionPolicy(default_mode=ExecutionMode.AUTO_SAFE)
    decision = policy.decide("unknown_action_xyz")
    assert decision.mode is ExecutionMode.AUTO_SAFE
    assert "默认" in decision.reason

    policy = ExecutionPolicy(default_mode=ExecutionMode.NEEDS_CONFIRMATION)
    decision = policy.decide("another_unknown")
    assert decision.mode is ExecutionMode.NEEDS_CONFIRMATION

    policy = ExecutionPolicy(default_mode=ExecutionMode.BLOCKED)
    blocked = policy.decide("yet_another")
    assert blocked.mode is ExecutionMode.BLOCKED


def test_execution_policy_auto_safe_full_set():
    from backend.app_services.execution_policy import ExecutionMode, ExecutionPolicy

    policy = ExecutionPolicy()
    for tool in [
        "get_stock_context",
        "get_daily_history",
        "search_stock_intel",
        "get_portfolio_snapshot",
        "get_active_risk_policy",
        "list_risk_policies",
        "evaluate_policy_risk",
        "analyze_portfolio_risk",
        "get_monitor_events",
        "get_monitor_rules",
        "evaluate_monitor_rules",
        "generate_draft_order",
        "create_pre_trade_review",
        "list_strategies",
        "run_strategy_backtest",
        "get_backtest_result",
        "list_report_templates",
        "generate_report",
        "get_report_quality",
        "list_rebalance_drafts",
        "get_rebalance_draft",
        "list_pre_trade_reviews",
        "list_paper_orders",
        "get_paper_portfolio",
        "analyze_paper_performance",
        "create_paper_portfolio_snapshot",
        "list_decision_journal",
        "get_decision_journal_entry",
        "summarize_decision_outcomes",
        "list_review_inbox",
        "summarize_review_inbox",
    ]:
        assert policy.decide(tool).mode is ExecutionMode.AUTO_SAFE, f"{tool} should be AUTO_SAFE"




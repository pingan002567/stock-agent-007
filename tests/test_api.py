from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import subprocess
import tempfile

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config.tools import DEFAULT_TOOLS
from backend.schemas import (
    HoldingPosition,
    PaperOrder,
    PaperOrderStatus,
    PriceSnapshot,
    RebalanceDraftDecisionNoteRequest,
    model_to_dict,
)
from backend.stock_domain.provider_router import ProviderRouter
from backend.stock_domain.providers import MockMarketDataProvider, ProviderError

CANONICAL_EXECUTION_GUARD = {
    "auto_trade": False,
    "place_real_order_enabled": False,
    "paper_trading": "sandbox_only",
    "real_order": "blocked",
}


def make_client(tmp_path):
    app = create_app(db_path=tmp_path / "api.sqlite3", files_root=tmp_path / "files")
    return TestClient(app)


def parse_sse_events(body: str) -> list[dict]:
    events = []
    for chunk in body.split("\n\n"):
        if not chunk.startswith("event: "):
            continue
        data_line = [line for line in chunk.splitlines() if line.startswith("data: ")][
            0
        ]
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


def _force_stub_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure AI runtime uses non-degraded stub regardless of host.

    *WORKBENCH_DEERFLOW_MODE=stub* puts the adapter into clean stub mode
    (not degraded embedded), which is what Copilot SSE tests expect.
    Clears API key env so auto-upgrade to direct mode is not attempted.
    """
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKBENCH_AI_API_KEY", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "stub")


def seed_review_inbox_pending_draft(client: TestClient):
    services = client.app.state.services
    return services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )


def test_health_and_app_shell(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKBENCH_AI_API_KEY", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_client.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("No module named 'deerflow'")),
    )
    client = make_client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert payload["runtime"] == "deerflow-adapter-stub"
    agent_runtime = payload["agent_runtime"]
    assert agent_runtime["mode"] == "embedded"
    assert agent_runtime["available"] is False
    assert agent_runtime["active_client"] == "stub"
    assert agent_runtime["degraded"] is True
    assert agent_runtime["degraded_reason"]
    assert agent_runtime["subagent_enabled"] is False
    assert agent_runtime["plan_mode"] is False
    assert agent_runtime["client_capabilities"] == []
    assert agent_runtime["thinking_enabled"] is True
    assert payload["stock_domain"] == "provider-router"
    assert "TeamRun" not in json.dumps(payload)
    assert payload["data_provider"]["akshare_available"] is False
    assert payload["data_provider"]["active_provider"] == "mock_adapter"
    assert payload["data_provider"]["fallback_provider"] == "mock_adapter"
    assert payload["data_provider"]["degraded"] is True
    assert (
        payload["data_provider"]["degraded_reason"]
        == "akshare optional dependency is not installed"
    )
    assert (
        payload["data_provider"]["capabilities"]["quote"]["active_provider"]
        == "mock_adapter"
    )
    assert (
        payload["data_provider"]["capabilities"]["market"]["active_provider"]
        == "mock_adapter"
    )

    app_shell = client.get("/app")
    assert app_shell.status_code == 200


def test_health_reports_fallback_when_embedded_import_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKBENCH_AI_API_KEY", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_client.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("No module named 'deerflow'")),
    )

    client = make_client(tmp_path)
    payload = client.get("/api/health").json()

    assert payload["runtime"] == "deerflow-adapter-stub"
    assert payload["agent_runtime"]["mode"] == "embedded"
    assert payload["agent_runtime"]["active_client"] == "stub"
    assert payload["agent_runtime"]["available"] is False
    assert payload["agent_runtime"]["degraded"] is True
    assert "No module named" in payload["agent_runtime"]["degraded_reason"]
    assert payload["agent_runtime"]["client_capabilities"] == []


def test_copilot_sse_uses_fake_embedded_deerflow_mapper(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def stream(self, **kwargs):
            yield (
                "messages-tuple",
                [SimpleNamespace(type="ai", content="fake embedded partial")],
            )
            yield (
                "messages-tuple",
                [
                    SimpleNamespace(
                        type="ai",
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "get_quote",
                                "args": {"symbol": "AAPL"},
                            }
                        ],
                    )
                ],
            )
            yield (
                "messages-tuple",
                [
                    SimpleNamespace(
                        type="tool",
                        name="get_quote",
                        tool_call_id="call_1",
                        content='{"last": 193.7}',
                    )
                ],
            )
            yield (
                "values",
                {
                    "messages": [
                        SimpleNamespace(type="ai", content="fake embedded partial")
                    ],
                    "status": "running",
                },
            )
            yield ("end", {"usage_metadata": {"total_tokens": 9}})

    deerflow_pkg = ModuleType("deerflow")
    client_mod = ModuleType("deerflow.client")
    client_mod.DeerFlowClient = FakeClient
    monkeypatch.setitem(sys.modules, "deerflow", deerflow_pkg)
    monkeypatch.setitem(sys.modules, "deerflow.client", client_mod)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")

    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "partial_answer",
        "tool_call",
        "tool_result",
        "reasoning",
        "final",
    ]
    assert events[1]["payload"]["text"] == "fake embedded partial"
    assert events[2]["payload"]["tool"] == events[3]["payload"]["tool"] == "get_quote"
    assert (
        events[2]["payload"]["call_id"] == events[3]["payload"]["call_id"] == "call_1"
    )
    assert events[2]["payload"]["arguments"] == {"symbol": "AAPL"}
    assert [
        event
        for event in events
        if event["type"] == "partial_answer"
        and event["payload"]["text"] == "fake embedded partial"
    ] == [events[1]]
    assert events[-1]["payload"]["usage"] == {"total_tokens": 9}
    assert "skill_trace" in events[-1]["payload"]
    # Embedded final always carries tool_evidence_refs; get_quote is not a workbench
    # tool, so it contributes no evidence and the list stays empty.
    assert events[-1]["payload"]["tool_evidence_refs"] == []


def test_copilot_sse_supports_sync_embedded_generator(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def stream(self, **kwargs):
            def raw_stream():
                yield (
                    "messages-tuple",
                    [SimpleNamespace(type="ai", content="sync embedded partial")],
                )
                yield ("end", {"usage_metadata": {"total_tokens": 4}})

            return raw_stream()

    deerflow_pkg = ModuleType("deerflow")
    client_mod = ModuleType("deerflow.client")
    client_mod.DeerFlowClient = FakeClient
    monkeypatch.setitem(sys.modules, "deerflow", deerflow_pkg)
    monkeypatch.setitem(sys.modules, "deerflow.client", client_mod)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")

    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "partial_answer",
        "final",
    ]
    assert events[1]["payload"]["text"] == "sync embedded partial"
    assert events[-1]["payload"]["usage"] == {"total_tokens": 4}


def test_stock_search_and_context(tmp_path):
    client = make_client(tmp_path)
    search = client.get("/api/stocks/search", params={"q": "腾讯"})
    assert search.status_code == 200
    assert search.json()["items"][0]["symbol"] == "HK00700"

    context = client.get("/api/stocks/AAPL/context")
    assert context.status_code == 200
    data = context.json()
    assert data["symbol"] == "AAPL"
    assert data["relation"]["in_holdings"] is True
    assert data["ai_state"]["risk_label"] == "集中度高"


def test_stock_history_intel_and_dashboard(tmp_path):
    client = make_client(tmp_path)
    for symbol in ["AAPL", "HK00700", "600519"]:
        history = client.get(f"/api/stocks/{symbol}/history", params={"days": 16})
        assert history.status_code == 200
        history_payload = history.json()
        assert history_payload["source"]
        assert "degraded" in history_payload
        assert "degraded_reason" in history_payload
        assert history_payload["items"]

        intel = client.get(f"/api/stocks/{symbol}/intel")
        assert intel.status_code == 200
        assert intel.json()["items"]

        dashboard = client.get(f"/api/stocks/{symbol}/dashboard")
        assert dashboard.status_code == 200
        dashboard_payload = dashboard.json()
        assert dashboard_payload["risk_bars"]
        assert dashboard_payload["stance_summary"]["valid_for"] == "1 个交易日"


def test_strategy_crud_backtests_and_archive_survive_delete(tmp_path):
    client = make_client(tmp_path)

    strategies = client.get("/api/strategies")
    assert strategies.status_code == 200
    assert strategies.json()["items"][0]["strategy_id"] == "concentration-control"

    created = client.post(
        "/api/strategies",
        json={
            "name": "Price Momentum",
            "strategy_type": "price_momentum",
            "risk_level": "medium",
            "universe": ["AAPL", "HK00700"],
            "parameters": {"lookback_days": 12, "momentum_threshold_pct": 1.5},
            "tags": ["momentum"],
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["strategy_id"] == "price-momentum"

    updated = client.put(
        f"/api/strategies/{created_payload['strategy_id']}",
        json={
            "strategy_id": created_payload["strategy_id"],
            "name": "Price Momentum",
            "strategy_type": "price_momentum",
            "risk_level": "high",
            "universe": ["AAPL"],
            "parameters": {"lookback_days": 10, "momentum_threshold_pct": 2},
            "tags": ["momentum", "fast"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["risk_level"] == "high"

    run = client.post(
        "/api/strategies/concentration-control/backtest",
        json={"period": {"days": 14}, "universe": ["AAPL"]},
    )
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["strategy_snapshot"]["strategy_id"] == "concentration-control"
    assert run_payload["execution_guard"]["auto_trade"] is False
    assert run_payload["metrics"]["sample_size"] == 1

    backtests = client.get("/api/strategies/concentration-control/backtests")
    assert backtests.status_code == 200
    assert backtests.json()["items"][0]["run_id"] == run_payload["run_id"]

    detail = client.get(f"/api/backtests/{run_payload['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_payload["run_id"]

    deleted = client.delete("/api/strategies/concentration-control")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    archived = client.get(f"/api/backtests/{run_payload['run_id']}")
    assert archived.status_code == 200
    assert (
        archived.json()["strategy_snapshot"]["strategy_id"] == "concentration-control"
    )
    assert client.get("/api/strategies/concentration-control").status_code == 404
    archived_list = client.get("/api/strategies/concentration-control/backtests")
    assert archived_list.status_code == 200
    assert archived_list.json()["items"][0]["run_id"] == run_payload["run_id"]


def test_research_creates_task_report_and_audit(tmp_path):
    client = make_client(tmp_path)
    research = client.post("/api/stocks/AAPL/research")
    assert research.status_code == 200
    data = research.json()
    assert data["task"]["task_id"].startswith("task_")
    assert data["report"]["report_id"].startswith("report_aapl_")
    assert "仅供研究" in data["report"]["content"]

    overview = client.get("/api/overview").json()
    assert overview["tasks"][0]["title"] == "AAPL 深研"
    assert overview["audit"][0]["action"] == "stock research created"
    assert overview["focus_stock"]["symbol"] == "AAPL"
    assert overview["monitor_summary"]["event_count"] >= 3


def test_report_templates_endpoint_returns_four_seed_templates(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/report-templates")
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["report_type"] for item in items} == {
        "stock_research",
        "monitor_review",
        "strategy_backtest",
        "paper_portfolio_review",
    }


def test_reports_generate_stock_research_and_quality(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "stock_research",
            "source_type": "stock",
            "source_id": "AAPL",
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["report_type"] == "stock_research"
    assert report["source_type"] == "stock"
    assert report["source_id"] == "AAPL"
    assert report["quality_status"] in {"passed", "warning"}

    quality = client.get(f"/api/reports/{report['report_id']}/quality")
    assert quality.status_code == 200
    quality_payload = quality.json()
    assert quality_payload["latest"]["report_id"] == report["report_id"]
    assert quality_payload["latest"]["status"] == report["quality_status"]


def test_reports_generate_rejects_template_report_type_mismatch(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "monitor_review",
            "source_type": "stock",
            "source_id": "AAPL",
            "template_id": "stock_research_default",
        },
    )
    assert response.status_code == 400
    assert "template/report_type mismatch" in response.json()["detail"]


def test_reports_generate_monitor_review_from_recent_monitor_event(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/monitor/rules",
        json={"symbol": "AAPL", "rule": "single_position_weight > 15%"},
    )
    created = client.post(
        "/api/monitor/evaluate-once", json={"source": "manual", "force": True}
    ).json()
    assert created["created"] >= 1

    events = client.get(
        "/api/monitor/events", params={"symbol": "AAPL", "limit": 1}
    ).json()["items"]
    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "monitor_review",
            "source_type": "monitor_event",
            "source_id": events[0]["event_id"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["report_type"] == "monitor_review"
    assert report["source_type"] == "monitor_event"
    assert report["candidate_actions"]
    assert report["execution_guard"]["auto_trade"] is False


def test_reports_generate_strategy_backtest_with_candidate_actions_and_auto_trade_false(
    tmp_path,
):
    client = make_client(tmp_path)
    run = client.post(
        "/api/strategies/concentration-control/backtest",
        json={"period": {"days": 14}, "universe": ["AAPL"]},
    ).json()

    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "strategy_backtest",
            "source_type": "backtest_run",
            "source_id": run["run_id"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["report_type"] == "strategy_backtest"
    assert report["degraded"] == run["degraded"]
    assert report["candidate_actions"]
    assert report["execution_guard"]["auto_trade"] is False


def test_reports_quality_rerun_appends_new_check_and_audit(tmp_path):
    client = make_client(tmp_path)
    report = client.post(
        "/api/reports/generate",
        json={
            "report_type": "stock_research",
            "source_type": "stock",
            "source_id": "AAPL",
        },
    ).json()
    initial = client.get(f"/api/reports/{report['report_id']}/quality").json()
    rerun = client.post(f"/api/reports/{report['report_id']}/rerun-quality")
    assert rerun.status_code == 200
    rerun_payload = rerun.json()
    assert rerun_payload["quality_status"] == report["quality_status"]

    updated = client.get(f"/api/reports/{report['report_id']}/quality").json()
    assert len(updated["items"]) == len(initial["items"]) + 1
    assert updated["latest"]["check_id"] != initial["latest"]["check_id"]

    export = client.post(f"/api/reports/{report['report_id']}/export")
    assert export.status_code == 200
    assert export.json()["quality_status"] == report["quality_status"]

    audit = client.get("/api/overview").json()["audit"]
    assert any(item["action"] == "report quality rerun" for item in audit)


def test_copilot_strategy_backtest_uses_known_tool_bridge_tool(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "回测 AAPL 策略",
            "page": "strategy",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    assert run["intent"] == "strategy_backtest"
    assert run["skill"] == "strategy-analyst"
    assert run["skills"] == ["strategy-analyst", "report-writer"]

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "run_strategy_backtest"
    assert events[3]["payload"]["tool"] == "run_strategy_backtest"
    assert events[3]["payload"]["result"]["execution_guard"]["auto_trade"] is False
    assert events[-1]["payload"]["execution_guard"]["research_only"] is True
    assert events[-1]["payload"]["execution_guard"]["auto_trade"] is False

    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [
        (item["tool"], item["status"], item["domain"])
        for item in detail["tool_executions"]
    ] == [("run_strategy_backtest", "succeeded", "strategy")]


def test_copilot_monitor_report_stream_includes_report_quality_and_disclaimer(
    tmp_path, monkeypatch
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    client.post(
        "/api/monitor/rules",
        json={"symbol": "AAPL", "rule": "single_position_weight > 15%"},
    )
    client.post("/api/monitor/evaluate-once", json={"source": "manual", "force": True})

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "把最近盯盘事件生成报告",
            "page": "monitor",
            "authority_level": "A2",
        },
    ).json()

    assert run["intent"] == "report_write"
    assert run["skills"] == ["stock-monitor", "report-writer"]

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "generate_report"
    assert events[3]["payload"]["result"]["report_type"] == "monitor_review"
    assert (
        events[-1]["payload"]["report_id"]
        == events[3]["payload"]["result"]["report_id"]
    )
    assert (
        events[-1]["payload"]["quality_status"]
        == events[3]["payload"]["result"]["quality_status"]
    )
    assert events[-1]["payload"]["disclaimer"] == "仅供研究，不构成投资建议。"


def test_monitor_events_include_multiple_severities(tmp_path):
    client = make_client(tmp_path)
    # Clear seed events so the fallback (monitor_tools.get_monitor_events,
    # which includes "high" and "medium") is used instead.
    repo = client.app.state.services.repo
    for event in repo.list_monitor_events(limit=100):
        repo.conn.execute(
            "DELETE FROM monitor_event WHERE event_id = ?", (event.event_id,)
        )
    repo.conn.commit()
    events = client.get("/api/monitor/events")
    assert events.status_code == 200
    severities = {item["severity"] for item in events.json()["items"]}
    assert {"high", "medium"}.issubset(severities)


def test_monitor_status_rules_evaluate_once_and_stream(tmp_path):
    client = make_client(tmp_path)

    status = client.get("/api/monitor/status")
    assert status.status_code == 200
    assert status.json()["status"] == "paused"

    started = client.post("/api/monitor/start")
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    saved = client.post(
        "/api/monitor/rules",
        json={"symbol": "AAPL", "rule": "single_position_weight > 15%"},
    )
    assert saved.status_code == 200
    assert saved.json()["rule_type"] == "single_position_weight_gt"

    rules = client.get("/api/monitor/rules")
    assert rules.status_code == 200
    rule_id = rules.json()["items"][0]["rule_id"]

    evaluated = client.post(
        "/api/monitor/evaluate-once", json={"source": "manual", "force": True}
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["created"] >= 1

    events = client.get(
        "/api/monitor/events", params={"symbol": "AAPL", "severity": "high", "limit": 5}
    )
    assert events.status_code == 200
    payload = events.json()
    assert payload["items"]
    assert payload["items"][0]["symbol"] == "AAPL"
    assert payload["items"][0]["source"] == "manual"
    assert payload["items"][0]["rule_id"] == rule_id

    overview = client.get("/api/overview").json()
    assert overview["monitor_summary"]["status"] == "running"
    assert overview["monitor_summary"]["event_count"] >= 1
    assert overview["monitor_summary"]["latest"]["rule_id"] == rule_id

    with client.stream("GET", "/api/monitor/stream") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    stream_events = parse_sse_events(body)
    assert [event["type"] for event in stream_events] == ["status", "events", "summary"]
    assert stream_events[0]["payload"]["status"] == "running"
    assert stream_events[1]["payload"]["items"]
    assert stream_events[2]["payload"]["event_count"] >= 1

    deleted = client.delete(f"/api/monitor/rules/{rule_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    paused = client.post("/api/monitor/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


def test_v04_stock_provider_endpoints_return_200_with_offline_mock_router(
    tmp_path, monkeypatch
):
    from backend.stock_domain.provider_router import ProviderRouter as _PR

    router = _PR(
        primary=type(
            "UnavailablePrimary",
            (),
            {"name": "akshare", "is_available": lambda self: True},
        )(),
        fallback=MockMarketDataProvider(),
    )
    router.repo = None
    monkeypatch.setattr("backend.stock_domain.provider_router.provider_router", router)
    monkeypatch.setattr("backend.stock_domain.history_tools.provider_router", router)
    monkeypatch.setattr("backend.stock_domain.intel_tools.provider_router", router)
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)

    context = client.get("/api/stocks/AAPL/context")
    assert context.status_code == 200

    hk_history = client.get("/api/stocks/HK00700/history", params={"days": 5})
    assert hk_history.status_code == 200
    hk_payload = hk_history.json()
    assert hk_payload["source"] == "mock_adapter"
    assert hk_payload["degraded"] is True
    assert hk_payload["degraded_reason"] is not None

    cn_history = client.get("/api/stocks/600519/history", params={"days": 5})
    assert cn_history.status_code == 200
    cn_payload = cn_history.json()
    assert cn_payload["source"] == "mock_adapter"
    assert cn_payload["degraded"] is True
    assert cn_payload["degraded_reason"] is not None


class RaisingApiPrimaryProvider:
    name = "akshare"

    def is_available(self) -> bool:
        return True

    def get_quote(self, symbol: str):
        raise ProviderError(f"quote failed for {symbol}")

    def get_history(self, symbol: str, days: int = 30) -> dict:
        raise ProviderError(f"history failed for {symbol}")

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError(f"intel failed for {symbol}")

    def get_market_review(self) -> dict:
        raise ProviderError("review failed")

    def get_sectors(self) -> dict:
        raise ProviderError("sectors failed")


def test_v04_health_and_monitor_report_fallback_after_primary_runtime_failure(
    tmp_path, monkeypatch
):
    router = ProviderRouter(
        primary=RaisingApiPrimaryProvider(), fallback=MockMarketDataProvider()
    )
    # Make _provider_for_market return the test primary so raises are
    # exercised regardless of which provider is configured for the market.
    router._provider_for_market = lambda market: router.primary
    monkeypatch.setattr("backend.stock_domain.quote_tools.provider_router", router)
    monkeypatch.setattr("backend.stock_domain.provider_router.provider_router", router)
    monkeypatch.setattr("backend.stock_domain.monitor_tools.provider_router", router)
    monkeypatch.setattr("backend.app.provider_router", router)
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)

    # Clear seed events so the fallback monitor events (which include
    # event_data_source_fallback) are used instead.
    repo = client.app.state.services.repo
    for event in repo.list_monitor_events(limit=100):
        repo.conn.execute(
            "DELETE FROM monitor_event WHERE event_id = ?", (event.event_id,)
        )
    repo.conn.commit()

    context = client.get("/api/stocks/600519/context")
    assert context.status_code == 200
    assert context.json()["price"]["degraded"] is True

    health = client.get("/api/health").json()
    assert health["data_provider"]["akshare_available"] is True
    assert health["data_provider"]["active_provider"] == "mock_adapter"
    assert health["data_provider"]["fallback_provider"] == "mock_adapter"
    assert health["data_provider"]["degraded"] is True
    assert (
        health["data_provider"]["degraded_reason"] == "akshare: quote failed for 600519"
    )
    assert (
        health["data_provider"]["capabilities"]["quote"]["degraded_reason"]
        == "akshare: quote failed for 600519"
    )

    monitor = client.get("/api/monitor/events").json()
    data_event = next(
        item
        for item in monitor["items"]
        if item["event_id"] == "event_data_source_fallback"
    )
    assert data_event["trigger_rule"] == "primary_provider_unavailable"
    assert any(
        item["type"] == "active_provider" and item["ref"] == "mock_adapter"
        for item in data_event["evidence"]
    )


def test_v04_market_review_and_sectors_keep_truthful_mock_source(tmp_path):
    client = make_client(tmp_path)

    review = client.get("/api/market/review")
    assert review.status_code == 200
    assert review.json()["source"] == "mock_adapter"
    assert review.json()["degraded"] is True
    assert review.json()["degraded_reason"] is not None

    sectors = client.get("/api/market/sectors")
    assert sectors.status_code == 200
    assert sectors.json()["source"] == "mock_adapter"
    assert sectors.json()["degraded"] is True
    assert sectors.json()["degraded_reason"] is not None
    assert sectors.json()["items"]


def test_parallel_demo_bootstrap_requests_share_sqlite_safely(tmp_path):
    client = make_client(tmp_path)
    paths = [
        "/api/overview",
        "/api/watchlist",
        "/api/holdings",
        "/api/holdings/risk",
        "/api/stocks/AAPL/context",
        "/api/tasks",
        "/api/reports",
        "/api/settings",
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda path: client.get(path).status_code, paths * 4))

    assert statuses == [200] * len(statuses)


def test_holdings_risk_and_copilot_chat(tmp_path):
    client = make_client(tmp_path)
    risk = client.get("/api/holdings/risk")
    assert risk.status_code == 200
    assert any(item["symbol"] == "AAPL" for item in risk.json()["risks"])
    assert risk.json()["risk_policy_ref"]["policy_id"] == "default-conservative"

    draft = client.post(
        "/api/holdings/rebalance-draft",
        json={"symbol": "AAPL", "target_weight_pct": 15},
    )
    assert draft.status_code == 200
    draft_payload = draft.json()
    assert draft_payload["draft_id"].startswith("draft_")
    assert draft_payload["draft_status"] == "pending_user_confirmation"
    assert draft_payload["authority_level"] == "A4"
    assert (
        draft_payload["output"]["draft_order"]["draft_id"] == draft_payload["draft_id"]
    )
    assert draft_payload["output"]["draft_order"]["auto_trade"] is False
    assert (
        draft_payload["output"]["draft_order"]["status"] == "pending_user_confirmation"
    )

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["run_id"].startswith("run_")
    assert payload["task_id"].startswith("task_")
    assert payload["skill"] == "risk-officer"


def test_risk_policy_api_active_create_update_activate_and_audit(tmp_path):
    client = make_client(tmp_path)

    active = client.get("/api/risk-policies/active")
    assert active.status_code == 200
    active_payload = active.json()
    assert active_payload["policy_id"] == "default-conservative"
    assert active_payload["rules"]["single_position_max_weight_pct"] == 15
    assert active_payload["rules"]["single_position_warning_weight_pct"] == 12
    assert active_payload["rules"]["sector_max_weight_pct"] == 35

    created = client.post(
        "/api/risk-policies",
        json={
            "policy_id": "balanced-growth",
            "name": "Balanced Growth",
            "description": "lighter concentration guard",
            "rules": {
                "single_position_max_weight_pct": 20,
                "single_position_warning_weight_pct": 16,
                "sector_max_weight_pct": 45,
                "draft_valid_hours": 12,
                "rebalance_min_delta_pct": 1.5,
                "monitor_default_cooldown_seconds": 900,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["policy_id"] == "balanced-growth"

    updated = client.put(
        "/api/risk-policies/balanced-growth",
        json={
            "policy_id": "ignored-on-put",
            "name": "Balanced Growth Plus",
            "description": "updated",
            "rules": {
                "single_position_max_weight_pct": 20,
                "single_position_warning_weight_pct": 17,
                "sector_max_weight_pct": 45,
                "draft_valid_hours": 18,
                "rebalance_min_delta_pct": 1.25,
                "monitor_default_cooldown_seconds": 1200,
            },
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Balanced Growth Plus"
    assert updated.json()["version"] >= 2

    activated = client.post("/api/risk-policies/balanced-growth/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    assert activated.json()["is_default"] is True

    policies = client.get("/api/risk-policies").json()["items"]
    flags = {
        item["policy_id"]: (item["is_active"], item["is_default"]) for item in policies
    }
    assert flags["balanced-growth"] == (True, True)
    assert flags["default-conservative"] == (False, False)

    risk = client.get("/api/holdings/risk").json()
    assert not any(
        item["symbol"] == "AAPL"
        and item["severity"] == "high"
        and item["kind"] == "single_position_max"
        for item in risk["risks"]
    )

    audit_actions = [
        item["action"] for item in client.get("/api/overview").json()["audit"]
    ]
    assert "risk policy created" in audit_actions
    assert "risk policy updated" in audit_actions
    assert "risk policy activated" in audit_actions


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        (
            {
                "policy_id": "invalid-thresholds",
                "name": "Invalid Thresholds",
                "rules": {
                    "single_position_max_weight_pct": 15,
                    "single_position_warning_weight_pct": 16,
                    "sector_max_weight_pct": 35,
                    "draft_valid_hours": 12,
                    "rebalance_min_delta_pct": 1.5,
                    "monitor_default_cooldown_seconds": 900,
                },
            },
            "/api/risk-policies",
        ),
        (
            {
                "policy_id": "invalid-draft-hours",
                "name": "Invalid Draft Hours",
                "rules": {
                    "single_position_max_weight_pct": 15,
                    "single_position_warning_weight_pct": 12,
                    "sector_max_weight_pct": 35,
                    "draft_valid_hours": -1,
                    "rebalance_min_delta_pct": 1.5,
                    "monitor_default_cooldown_seconds": 900,
                },
            },
            "/api/risk-policies",
        ),
        (
            {
                "policy_id": "ignored-on-put",
                "name": "Invalid Cooldown",
                "rules": {
                    "single_position_max_weight_pct": 15,
                    "single_position_warning_weight_pct": 12,
                    "sector_max_weight_pct": 35,
                    "draft_valid_hours": 12,
                    "rebalance_min_delta_pct": 1.5,
                    "monitor_default_cooldown_seconds": -1,
                },
            },
            "/api/risk-policies/default-conservative",
        ),
    ],
)
def test_risk_policy_api_rejects_invalid_rule_payloads(tmp_path, payload, path):
    client = make_client(tmp_path)

    response = (
        client.post(path, json=payload)
        if path == "/api/risk-policies"
        else client.put(path, json=payload)
    )

    assert response.status_code in {400, 422}


def test_rebalance_draft_api_persists_reads_confirms_rejects_and_expires(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services

    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 15}
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["draft_id"].startswith("draft_")
    assert created_payload["status"] == "pending_user_confirmation"
    assert created_payload["auto_trade"] is False
    assert created_payload["output"]["execution_guard"] == CANONICAL_EXECUTION_GUARD

    listed = client.get("/api/rebalance-drafts")
    assert listed.status_code == 200
    assert any(
        item["draft_id"] == created_payload["draft_id"]
        for item in listed.json()["items"]
    )

    detail = client.get(f"/api/rebalance-drafts/{created_payload['draft_id']}")
    assert detail.status_code == 200
    assert detail.json()["draft_id"] == created_payload["draft_id"]

    confirmed = client.post(
        f"/api/rebalance-drafts/{created_payload['draft_id']}/confirm",
        json={"note": "人工确认，仅留审计"},
    )
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    assert confirmed_payload["status"] == "confirmed_no_execution"
    assert confirmed_payload["note"] == "人工确认，仅留审计"
    assert confirmed_payload["output"]["execution_guard"] == CANONICAL_EXECUTION_GUARD
    audit = json.dumps(
        [item.model_dump(mode="json") for item in services.repo.list_audit(limit=50)],
        ensure_ascii=False,
    )
    assert "rebalance draft confirmed" in audit

    rejected = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 14}
    )
    rejected_id = rejected.json()["draft_id"]
    rejected_response = client.post(
        f"/api/rebalance-drafts/{rejected_id}/reject",
        json={"note": "风险判断不接受"},
    )
    assert rejected_response.status_code == 200
    assert rejected_response.json()["status"] == "rejected"
    assert (
        rejected_response.json()["output"]["execution_guard"]
        == CANONICAL_EXECUTION_GUARD
    )
    audit = json.dumps(
        [model_to_dict(item) for item in services.repo.list_audit(limit=50)],
        ensure_ascii=False,
    )
    assert "rebalance draft rejected" in audit

    expired = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 13}
    ).json()
    services = client.app.state.services
    stale = services.repo.get_rebalance_draft(expired["draft_id"])
    stale.valid_until = "2000-01-01T00:00:00+00:00"
    stale.updated_at = "2000-01-01T00:00:00+00:00"
    services.repo.save_rebalance_draft(stale)

    expired_list = client.get("/api/rebalance-drafts", params={"status": "expired"})
    assert expired_list.status_code == 200
    assert any(
        item["draft_id"] == expired["draft_id"] and item["status"] == "expired"
        for item in expired_list.json()["items"]
    )

    pending_list = client.get(
        "/api/rebalance-drafts", params={"status": "pending_user_confirmation"}
    )
    assert pending_list.status_code == 200
    assert all(
        item["draft_id"] != expired["draft_id"] for item in pending_list.json()["items"]
    )
    assert all(
        item["status"] == "pending_user_confirmation"
        for item in pending_list.json()["items"]
    )

    expired_confirm = client.post(
        f"/api/rebalance-drafts/{expired['draft_id']}/confirm",
        json={"note": "过期后仍尝试确认"},
    )
    assert expired_confirm.status_code == 409
    assert "regenerate" in expired_confirm.json()["detail"]
    expired_detail = client.get(f"/api/rebalance-drafts/{expired['draft_id']}")
    assert expired_detail.status_code == 200
    assert expired_detail.json()["status"] == "expired"
    assert (
        expired_detail.json()["output"]["execution_guard"] == CANONICAL_EXECUTION_GUARD
    )


def test_pre_trade_review_api_creates_review_and_writes_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    client = make_client(tmp_path)
    services = client.app.state.services
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    confirmed = client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm",
        json={"note": "ready for review"},
    )
    assert confirmed.status_code == 200

    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    )
    assert review.status_code == 200
    payload = review.json()
    assert payload["review_id"].startswith("review_")
    assert payload["status"] == "passed"
    assert payload["execution_guard"] == CANONICAL_EXECUTION_GUARD

    listed = client.get(
        "/api/pre-trade-reviews", params={"draft_id": created["draft_id"]}
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["review_id"] == payload["review_id"]

    detail = client.get(f"/api/pre-trade-reviews/{payload['review_id']}")
    assert detail.status_code == 200
    assert detail.json()["review_id"] == payload["review_id"]
    audit = json.dumps(
        [model_to_dict(item) for item in services.repo.list_audit(limit=50)],
        ensure_ascii=False,
    )
    assert "pre-trade review created" in audit


@pytest.mark.parametrize("draft_status", ["pending", "rejected", "expired"])
def test_pre_trade_review_api_returns_409_for_non_confirmed_drafts(
    tmp_path, draft_status
):
    client = make_client(tmp_path)
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 13}
    ).json()
    draft_id = created["draft_id"]

    if draft_status == "rejected":
        response = client.post(
            f"/api/rebalance-drafts/{draft_id}/reject", json={"note": "no"}
        )
        assert response.status_code == 200
    elif draft_status == "expired":
        services = client.app.state.services
        stale = services.repo.get_rebalance_draft(draft_id)
        stale.valid_until = "2000-01-01T00:00:00+00:00"
        stale.updated_at = "2000-01-01T00:00:00+00:00"
        services.repo.save_rebalance_draft(stale)

    review = client.post("/api/pre-trade-reviews", json={"draft_id": draft_id})
    assert review.status_code == 409


def test_pre_trade_review_api_blocks_policy_violation_and_paper_order_creation(
    tmp_path,
):
    client = make_client(tmp_path)
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 16}
    ).json()
    confirmed = client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm",
        json={"note": "ready for review"},
    )
    assert confirmed.status_code == 200

    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    )
    assert review.status_code == 200
    payload = review.json()
    assert payload["status"] == "blocked"
    assert "single_position_max_weight_exceeded" in payload["blocker_codes"]

    order = client.post("/api/paper-orders", json={"review_id": payload["review_id"]})
    assert order.status_code == 409


def test_paper_order_api_fills_from_passed_review_and_keeps_holdings_unchanged(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    client = make_client(tmp_path)
    before = client.get("/api/holdings").json()["items"]
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    ).json()

    order = client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    assert order.status_code == 200
    payload = order.json()
    assert payload["status"] == "paper_filled"
    assert payload["execution_guard"] == CANONICAL_EXECUTION_GUARD
    assert payload["side"] == "SELL"

    listed = client.get("/api/paper-orders", params={"review_id": review["review_id"]})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["order_id"] == payload["order_id"]

    cancel = client.post(
        f"/api/paper-orders/{payload['order_id']}/cancel",
        json={"note": "sandbox cancel"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "paper_cancelled"

    after = client.get("/api/holdings").json()["items"]
    assert after == before


def test_paper_order_api_preserves_degraded_quote_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=188.5,
            change_pct=-0.5,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=True,
            degraded_reason="primary feed unavailable",
        ),
    )
    client = make_client(tmp_path)
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    ).json()
    assert review["status"] == "warning"

    order = client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    assert order.status_code == 200
    payload = order.json()
    assert payload["status"] == "paper_filled"
    assert payload["quote_degraded"] is True
    assert payload["quote_degraded_reason"] == "primary feed unavailable"
    assert payload["paper_price_source"] == "mock_adapter"


def test_paper_order_api_rejects_tampered_saved_review_execution_guard(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    client = make_client(tmp_path)
    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    ).json()

    services = client.app.state.services
    saved_review = services.repo.get_pre_trade_review(review["review_id"])
    assert saved_review is not None
    saved_review.execution_guard["paper_trading"] = "live"
    services.repo.save_pre_trade_review(saved_review)

    order = client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    assert order.status_code == 409


def test_paper_portfolio_api_uses_persisted_baseline_and_does_not_follow_holdings_import(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    holdings = client.app.state.services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    portfolio = client.get("/api/paper-portfolio")
    assert portfolio.status_code == 200
    payload = portfolio.json()
    baseline_id = payload["summary"]["baseline_id"]
    baseline_aapl = next(
        item for item in payload["projection"]["positions"] if item["symbol"] == "AAPL"
    )
    assert payload["summary"]["initial_cash"] == 0
    assert payload["summary"]["initial_nav"] == pytest.approx(
        sum(item.market_value for item in holdings)
    )

    imported = client.post(
        "/api/holdings/import-confirm",
        json=[
            {
                "symbol": "AAPL",
                "name": "Apple",
                "quantity": 1,
                "market_value": 1,
                "weight_pct": 0.1,
            }
        ],
    )
    assert imported.status_code == 200

    drifted = client.get("/api/paper-portfolio")
    assert drifted.status_code == 200
    drift_payload = drifted.json()
    drift_aapl = next(
        item
        for item in drift_payload["projection"]["positions"]
        if item["symbol"] == "AAPL"
    )

    assert drift_payload["summary"]["baseline_id"] == baseline_id
    assert drift_aapl["quantity"] == pytest.approx(baseline_aapl["quantity"])
    assert drift_aapl["market_value"] == pytest.approx(baseline_aapl["market_value"])


def test_paper_portfolio_api_positions_change_from_filled_orders_without_touching_holdings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    client = make_client(tmp_path)
    services = client.app.state.services
    base_holdings = client.get("/api/holdings").json()["items"]
    base_prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in services.repo.list_holdings()
    }
    base_prices["HK00700"] = 386.8
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=base_prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    baseline = client.get("/api/paper-portfolio").json()
    before_hk = next(
        item
        for item in baseline["projection"]["positions"]
        if item["symbol"] == "HK00700"
    )

    created = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{created['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": created["draft_id"]}
    ).json()
    order = client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    assert order.status_code == 200

    services.repo.save_paper_order(
        PaperOrder(
            order_id="paper_cancelled_ignored_api",
            review_id="review_cancelled",
            source_draft_id="draft_cancelled",
            status=PaperOrderStatus.PAPER_CANCELLED,
            symbol="TSLA",
            side="BUY",
            target_weight_pct=4,
            delta_weight_pct=4,
            paper_price=200,
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:10:00+00:00",
            paper_quantity_estimate=5,
            paper_notional_estimate=1000,
        )
    )
    services.repo.save_paper_order(
        PaperOrder(
            order_id="paper_rejected_ignored_api",
            review_id="review_rejected",
            source_draft_id="draft_rejected",
            status=PaperOrderStatus.PAPER_REJECTED,
            symbol="NVDA",
            side="BUY",
            target_weight_pct=4,
            delta_weight_pct=4,
            paper_price=100,
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:11:00+00:00",
            paper_quantity_estimate=5,
            paper_notional_estimate=500,
        )
    )

    positions = client.get("/api/paper-portfolio/positions")
    assert positions.status_code == 200
    position_items = positions.json()["items"]
    after_hk = next(item for item in position_items if item["symbol"] == "HK00700")

    assert after_hk["quantity"] != pytest.approx(before_hk["quantity"])
    assert after_hk["weight_pct"] != pytest.approx(before_hk["weight_pct"])
    assert all(item["symbol"] not in {"TSLA", "NVDA"} for item in position_items)
    assert client.get("/api/holdings").json()["items"] == base_holdings


def test_paper_portfolio_api_sell_warning_degraded_performance_and_snapshot_audit(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    services = client.app.state.services
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }

    def fake_quote(symbol: str) -> PriceSnapshot:
        degraded = symbol.upper() == "HK00700"
        return PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=degraded,
            degraded_reason="primary feed unavailable" if degraded else None,
        )

    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        fake_quote,
    )
    baseline = client.get("/api/paper-portfolio").json()
    aapl = next(
        item for item in baseline["projection"]["positions"] if item["symbol"] == "AAPL"
    )
    services.repo.save_paper_order(
        PaperOrder(
            order_id="paper_sell_aapl_api",
            review_id="review_aapl_api",
            source_draft_id="draft_aapl_api",
            status=PaperOrderStatus.PAPER_FILLED,
            symbol="AAPL",
            side="SELL",
            target_weight_pct=0,
            delta_weight_pct=-25,
            paper_price=prices["AAPL"],
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:12:00+00:00",
            paper_quantity_estimate=aapl["quantity"] + 10,
            paper_notional_estimate=(aapl["quantity"] + 10) * prices["AAPL"],
            filled_at="2026-05-13T08:12:00+00:00",
            created_at="2026-05-13T08:12:00+00:00",
        )
    )

    portfolio = client.get("/api/paper-portfolio")
    performance = client.get("/api/paper-portfolio/performance")
    assert portfolio.status_code == 200
    assert performance.status_code == 200
    assert portfolio.json()["projection"]["degraded"] is True
    assert any(
        item["code"] == "sell_clamped_no_short"
        for item in portfolio.json()["projection"]["warnings"]
    )
    assert performance.json()["degraded"] is True
    assert (
        performance.json()["quotes"]["HK00700"]["degraded_reason"]
        == "primary feed unavailable"
    )

    snapshot = client.post("/api/paper-portfolio/snapshots")
    assert snapshot.status_code == 200
    snapshot_payload = snapshot.json()
    assert snapshot_payload["payload"]["positions"]
    assert snapshot_payload["payload"]["quotes"]["HK00700"]["degraded"] is True

    listed = client.get("/api/paper-portfolio/snapshots")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["snapshot_id"] == snapshot_payload["snapshot_id"]
    detail = client.get(
        f"/api/paper-portfolio/snapshots/{snapshot_payload['snapshot_id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["snapshot_id"] == snapshot_payload["snapshot_id"]
    assert any(
        item["action"] == "paper portfolio snapshot created"
        for item in client.get("/api/overview").json()["audit"]
    )


def test_report_api_generates_paper_portfolio_review_from_snapshot_without_live_quote(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    services = client.app.state.services
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    snapshot = client.post("/api/paper-portfolio/snapshots").json()
    monkeypatch.setattr(
        "backend.stock_domain.provider_router.provider_router.get_quote",
        lambda symbol: (_ for _ in ()).throw(
            RuntimeError("live quote should not be used")
        ),
    )

    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "paper_portfolio_review",
            "source_type": "paper_portfolio_snapshot",
            "source_id": snapshot["snapshot_id"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["report_type"] == "paper_portfolio_review"
    assert report["source_type"] == "paper_portfolio_snapshot"
    assert report["execution_guard"]["auto_trade"] is False


def test_closed_loop_api_acceptance_golden_path_keeps_holdings_unchanged_and_links_evidence(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    services = client.app.state.services
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8 if symbol.upper() == "HK00700" else 193.7,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    prices["HK00700"] = 386.8
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    holdings_before = client.get("/api/holdings").json()["items"]

    risk = client.get("/api/holdings/risk")
    assert risk.status_code == 200
    assert risk.json()["decision"]

    draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    )
    assert draft.status_code == 200
    draft_payload = draft.json()
    assert draft_payload["status"] == "pending_user_confirmation"

    confirmed = client.post(
        f"/api/rebalance-drafts/{draft_payload['draft_id']}/confirm",
        json={"note": "golden path confirm"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed_no_execution"

    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": draft_payload["draft_id"]}
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["status"] == "passed"

    paper_order = client.post(
        "/api/paper-orders", json={"review_id": review_payload["review_id"]}
    )
    assert paper_order.status_code == 200
    paper_order_payload = paper_order.json()
    assert paper_order_payload["status"] == "paper_filled"

    performance = client.get("/api/paper-portfolio/performance")
    assert performance.status_code == 200
    assert performance.json()["since_baseline"]["initial_equity"] > 0

    snapshot = client.post("/api/paper-portfolio/snapshots")
    assert snapshot.status_code == 200
    snapshot_payload = snapshot.json()
    assert snapshot_payload["payload"]["positions"]

    report = client.post(
        "/api/reports/generate",
        json={
            "report_type": "paper_portfolio_review",
            "source_type": "paper_portfolio_snapshot",
            "source_id": snapshot_payload["snapshot_id"],
        },
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["source_id"] == snapshot_payload["snapshot_id"]

    entry = next(
        item
        for item in client.get("/api/decision-journal").json()["items"]
        if item["decision_id"] == draft_payload["decision_id"]
    )
    assert entry["paper_order_id"] == paper_order_payload["order_id"]
    assert entry["snapshot_id"] is None
    assert entry["report_id"] is None

    linked = client.post(
        f"/api/decision-journal/{entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot_payload["snapshot_id"]},
    )
    assert linked.status_code == 200
    linked_payload = linked.json()
    assert linked_payload["snapshot_id"] == snapshot_payload["snapshot_id"]
    assert linked_payload["report_id"] == report_payload["report_id"]

    closed = client.post(
        f"/api/decision-journal/{entry['entry_id']}/close",
        json={"close_note": "golden path complete"},
    )
    assert closed.status_code == 200
    closed_payload = closed.json()
    assert closed_payload["status"] == "closed"
    assert closed_payload["paper_order_id"] == paper_order_payload["order_id"]
    assert closed_payload["snapshot_id"] == snapshot_payload["snapshot_id"]
    assert closed_payload["report_id"] == report_payload["report_id"]
    assert closed_payload["chain"]["report"]["report_id"] == report_payload["report_id"]

    review_item_key = f"pre_trade_review:{review_payload['review_id']}"
    inbox_before_done = client.get("/api/review-inbox").json()["items"]
    assert any(item["item_key"] == review_item_key for item in inbox_before_done)
    done = client.post(
        f"/api/review-inbox/{review_item_key}/mark-done",
        json={"note": "closed-loop archived"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "done"
    inbox_after_done = client.get("/api/review-inbox").json()["items"]
    assert all(item["item_key"] != review_item_key for item in inbox_after_done)

    review_detail = client.get(f"/api/pre-trade-reviews/{review_payload['review_id']}")
    assert review_detail.status_code == 200
    assert review_detail.json()["status"] == review_payload["status"]
    journal_detail = client.get(f"/api/decision-journal/{entry['entry_id']}")
    assert journal_detail.status_code == 200
    assert journal_detail.json()["status"] == "closed"
    assert journal_detail.json()["report_id"] == report_payload["report_id"]

    summary = client.get("/api/decision-journal/summary")
    assert summary.status_code == 200
    assert summary.json()["paper_tracked_count"] == 1
    assert summary.json()["closed_count"] == 1

    holdings_after = client.get("/api/holdings").json()["items"]
    assert holdings_after == holdings_before

    audit = json.dumps(
        [model_to_dict(item) for item in services.repo.list_audit(limit=50)],
        ensure_ascii=False,
    )
    for marker in [
        "holdings risk review",
        "pre-trade review created",
        "paper order created",
        "paper portfolio snapshot created",
        "report generated",
        "decision journal snapshot linked",
        "decision journal entry closed",
    ]:
        assert marker in audit


def test_copilot_sse_stream_contains_final_disclaimer(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: reasoning" in body
    assert "event: skill_trace" in body
    assert "event: final" in body
    assert "risk-officer" in body
    assert "report-writer" in body
    parsed_events = parse_sse_events(body)
    assert [event["type"] for event in parsed_events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert parsed_events[2]["payload"]["tool"] == "evaluate_policy_risk"
    assert (
        parsed_events[3]["payload"]["result"]["risk_policy_ref"]["policy_id"]
        == "default-conservative"
    )
    assert {event["run_id"] for event in parsed_events} == {run["run_id"]}
    assert {event["task_id"] for event in parsed_events} == {run["task_id"]}
    final_chunks = [
        chunk for chunk in body.split("\n\n") if chunk.startswith("event: final")
    ]
    assert final_chunks
    data_line = [
        line for line in final_chunks[0].splitlines() if line.startswith("data: ")
    ][0]
    event = json.loads(data_line.removeprefix("data: "))
    assert "disclaimer" in event["payload"]
    assert [item["skill"] for item in event["payload"]["skill_trace"]] == [
        "stock-researcher",
        "risk-officer",
        "report-writer",
    ]
    assert all(
        {"step", "skill", "status", "handoff"} <= set(item)
        for item in event["payload"]["skill_trace"]
    )


def test_task_detail_and_stream_surface_tool_execution_ledger(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "分析 AAPL 风险",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        _ = "".join(response.iter_text())

    task_list = client.get("/api/tasks").json()["items"]
    task_item = next(item for item in task_list if item["task_id"] == run["task_id"])
    assert "tool_executions" not in task_item

    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert detail["task_id"] == run["task_id"]
    assert [
        (item["tool"], item["status"], item["call_id"], item["source_mode"])
        for item in detail["tool_executions"]
    ] == [("evaluate_policy_risk", "succeeded", "call_evaluate_policy_risk", "stub")]
    assert detail["tool_executions"][0]["run_id"] == run["run_id"]
    assert detail["tool_executions"][0]["domain"] == "risk"
    assert detail["tool_executions"][0]["arguments"] == {}
    assert detail["tool_executions"][0]["result_summary"]

    stream = client.get(f"/api/tasks/{run['task_id']}/stream")
    assert stream.status_code == 200
    events = parse_sse_events(stream.text)
    assert [event["type"] for event in events] == ["reasoning", "tool_result", "final"]
    assert events[0]["payload"]["phase"] == "task_snapshot"
    assert events[0]["payload"]["task"]["task_id"] == run["task_id"]
    assert events[1]["payload"]["tool"] == "evaluate_policy_risk"
    assert events[1]["payload"]["domain"] == "risk"
    assert events[1]["payload"]["arguments"] == {}
    assert events[1]["payload"]["status"] == "succeeded"
    assert events[1]["payload"]["result_summary"]
    assert events[-1]["payload"]["tool_execution_count"] == 1


def test_task_stream_replays_blocked_tool_execution_as_error(tmp_path):
    client = make_client(tmp_path)

    class FakeClient:
        async def stream(self, **kwargs):
            from backend.agent_runtime.tools import generate_draft_order

            yield (
                "messages-tuple",
                [
                    {
                        "type": "ai",
                        "content": "",
                        "id": "msg_ai1",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "name": "generate_draft_order",
                                "args": {"symbol": "AAPL"},
                            }
                        ],
                    }
                ],
            )
            # Mimic the real agent invoking the StructuredTool — _tool._run enforces
            # the request authority (A2 < A4) and records the blocked execution.
            result = generate_draft_order.invoke({"symbol": "AAPL"})
            yield (
                "messages-tuple",
                [{"type": "tool", "name": "generate_draft_order",
                  "tool_call_id": "call_1", "content": result, "id": "msg_tool1"}],
            )
            yield ("end", {"usage_metadata": {"total_tokens": 7}})

    client.app.state.services.copilot_service.deerflow.client = FakeClient()
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "研究 AAPL",
            "page": "stock",
            "symbol": "AAPL",
            "authority_level": "A2",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        _ = "".join(response.iter_text())

    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [(item["tool"], item["status"]) for item in detail["tool_executions"]] == [
        ("generate_draft_order", "blocked")
    ]

    replay = client.get(f"/api/tasks/{run['task_id']}/stream")
    events = parse_sse_events(replay.text)
    assert [event["type"] for event in events] == ["reasoning", "error", "final"]
    assert events[1]["payload"]["tool"] == "generate_draft_order"
    assert events[1]["payload"]["domain"] == "planner"
    # Execution-path records the validated args (schema default filled in).
    assert events[1]["payload"]["arguments"] == {"symbol": "AAPL", "target_weight_pct": 15.0}
    assert events[1]["payload"]["status"] == "blocked"
    assert "requires A4" in events[1]["payload"]["error"]


def test_copilot_rebalance_trace_keeps_execution_disabled(tmp_path, monkeypatch):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    run_response = client.post(
        "/api/copilot/chat",
        json={
            "message": "把 AAPL 降到 15% 并生成调仓方案",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["skill"] == "rebalance-planner"
    assert run["skills"] == [
        "stock-researcher",
        "risk-officer",
        "rebalance-planner",
        "report-writer",
        "execution-agent-disabled",
    ]

    tasks = client.get("/api/tasks").json()["items"]
    task = next(item for item in tasks if item["task_id"] == run["task_id"])
    assert [item["skill"] for item in task["skill_trace"]] == run["skills"]
    assert task["skill_trace"][-1]["status"] == "blocked"

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: skill_trace" in body
    assert "execution-agent-disabled" in body
    assert "real order execution is disabled in V1" in body
    events = parse_sse_events(body)
    final_event = [event for event in events if event["type"] == "final"][0]
    assert final_event["payload"]["execution_guard"]["auto_trade"] is False
    assert final_event["payload"]["execution_guard"]["status"] == "real_order_disabled"
    assert (
        final_event["payload"]["skill_trace"][-1]["skill"] == "execution-agent-disabled"
    )
    assert (
        "draft_order_guard:auto_trade_false"
        in final_event["payload"]["tool_evidence_refs"]
    )
    assert final_event["payload"]["draft_id"].startswith("draft_")
    assert final_event["payload"]["draft_status"] == "pending_user_confirmation"


def test_copilot_pre_trade_review_stream_returns_review_without_creating_paper_order(
    tmp_path,
    monkeypatch,
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 10}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{draft['draft_id']}/confirm", json={"note": "ready"}
    )

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "审查这个 AAPL 拟单是否适合执行",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "create_pre_trade_review"
    assert events[2]["payload"]["arguments"] == {"draft_id": draft["draft_id"]}
    assert events[3]["payload"]["tool"] == "create_pre_trade_review"
    final_payload = events[-1]["payload"]
    assert final_payload["review_id"].startswith("review_")
    assert final_payload["status"] in {"passed", "warning", "blocked"}
    assert "blockers" in final_payload
    assert final_payload["execution_guard"]["auto_trade"] is False
    assert client.get("/api/paper-orders").json()["items"] == []


def test_copilot_pre_trade_review_stream_fails_without_confirmed_draft_and_records_failed_ledger(
    tmp_path,
    monkeypatch,
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    services = client.app.state.services

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "审查这个 AAPL 拟单是否适合执行",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "error",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "create_pre_trade_review"
    assert events[3]["payload"]["tool"] == "create_pre_trade_review"
    assert "confirm a draft first" in events[3]["payload"]["error"]
    assert events[-1]["payload"]["runtime_error"]
    assert services.repo.list_pre_trade_reviews(limit=None) == []
    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [
        (item["tool"], item["status"], item["domain"])
        for item in detail["tool_executions"]
    ] == [("create_pre_trade_review", "failed", "planner")]


def test_copilot_paper_portfolio_review_uses_read_only_tool_chain_without_creating_orders(
    tmp_path, monkeypatch
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    services = client.app.state.services
    holdings = client.app.state.services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    before_counts = {
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "复盘 paper 调仓效果",
            "page": "holdings",
            "authority_level": "A4",
        },
    ).json()

    assert run["intent"] == "paper_portfolio_review"
    assert run["skills"] == ["risk-officer"]

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "analyze_paper_performance"
    assert events[3]["payload"]["tool"] == "analyze_paper_performance"
    assert events[3]["payload"]["result"]["since_baseline"]["initial_equity"] > 0
    assert client.get("/api/paper-orders").json()["items"] == []

    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [
        (item["tool"], item["status"], item["domain"])
        for item in detail["tool_executions"]
    ] == [("analyze_paper_performance", "succeeded", "paper-portfolio")]
    after_counts = {
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }
    assert after_counts == before_counts


def test_decision_journal_api_filters_summary_and_snapshot_linking(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    services = client.app.state.services
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8 if symbol.upper() == "AAPL" else 300.0,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    first_draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 15}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{first_draft['draft_id']}/confirm",
        json={"note": "ready"},
    )
    first_review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": first_draft["draft_id"]}
    ).json()
    first_order = client.post(
        "/api/paper-orders", json={"review_id": first_review["review_id"]}
    ).json()
    first_entry = client.get("/api/decision-journal").json()["items"][0]
    snapshot = client.post("/api/paper-portfolio/snapshots").json()

    explicit = client.post(
        f"/api/decision-journal/{first_entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot["snapshot_id"]},
    )
    assert explicit.status_code == 200
    assert explicit.json()["snapshot_id"] == snapshot["snapshot_id"]

    idempotent = client.post(
        f"/api/decision-journal/{first_entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot["snapshot_id"]},
    )
    assert idempotent.status_code == 200
    assert idempotent.json()["snapshot_id"] == snapshot["snapshot_id"]

    second_draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{second_draft['draft_id']}/confirm",
        json={"note": "ready"},
    )
    second_review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": second_draft["draft_id"]}
    ).json()
    client.post("/api/paper-orders", json={"review_id": second_review["review_id"]})
    second_entry = next(
        item
        for item in client.get("/api/decision-journal").json()["items"]
        if item["decision_id"] == second_draft["decision_id"]
    )

    conflict = client.post(
        f"/api/decision-journal/{second_entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot["snapshot_id"]},
    )
    assert conflict.status_code == 409

    latest_snapshot = client.post("/api/paper-portfolio/snapshots").json()
    omitted = client.post(
        f"/api/decision-journal/{second_entry['entry_id']}/link-snapshot", json={}
    )
    assert omitted.status_code == 200
    assert omitted.json()["snapshot_id"] == latest_snapshot["snapshot_id"]

    filtered_symbol = client.get("/api/decision-journal", params={"symbol": "AAPL"})
    assert filtered_symbol.status_code == 200
    assert [item["symbol"] for item in filtered_symbol.json()["items"]] == ["AAPL"]

    filtered_status = client.get(
        "/api/decision-journal", params={"status": "paper_tracked"}
    )
    assert filtered_status.status_code == 200
    assert any(
        item["entry_id"] == first_entry["entry_id"]
        for item in filtered_status.json()["items"]
    )

    filtered_source = client.get(
        "/api/decision-journal", params={"source_type": "paper_portfolio_snapshot"}
    )
    assert filtered_source.status_code == 200
    assert {item["entry_id"] for item in filtered_source.json()["items"]} == {
        first_entry["entry_id"],
        second_entry["entry_id"],
    }

    summary = client.get("/api/decision-journal/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_suggestions"] == 2
    assert payload["paper_tracked_count"] == 2
    assert payload["closed_count"] == 0
    assert isinstance(payload["average_paper_pnl"], float)

    empty_client = make_client(tmp_path / "empty-journal")
    empty_draft = empty_client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 15}
    ).json()
    empty_entry = empty_client.get("/api/decision-journal").json()["items"][0]
    missing = empty_client.post(
        f"/api/decision-journal/{empty_entry['entry_id']}/link-snapshot", json={}
    )
    assert missing.status_code == 404


def test_decision_journal_close_endpoint_requires_tracking_then_is_idempotent(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path)
    services = client.app.state.services
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 15}
    ).json()
    entry = client.get("/api/decision-journal").json()["items"][0]
    blocked_without_order = client.post(
        f"/api/decision-journal/{entry['entry_id']}/close", json={}
    )
    assert blocked_without_order.status_code == 409

    client.post(
        f"/api/rebalance-drafts/{draft['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": draft["draft_id"]}
    ).json()
    client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    tracked_entry = client.get("/api/decision-journal").json()["items"][0]
    blocked_without_snapshot = client.post(
        f"/api/decision-journal/{tracked_entry['entry_id']}/close", json={}
    )
    assert blocked_without_snapshot.status_code == 409

    snapshot = client.post("/api/paper-portfolio/snapshots").json()
    client.post(
        f"/api/decision-journal/{tracked_entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot["snapshot_id"]},
    )

    closed = client.post(
        f"/api/decision-journal/{tracked_entry['entry_id']}/close",
        json={"close_note": "settled"},
    )
    assert closed.status_code == 200
    closed_payload = closed.json()
    assert closed_payload["status"] == "closed"
    assert closed_payload["closed_at"] is not None
    assert closed_payload["close_note"] == "settled"

    again = client.post(
        f"/api/decision-journal/{tracked_entry['entry_id']}/close",
        json={"close_note": "ignored"},
    )
    assert again.status_code == 200
    assert again.json()["status"] == "closed"
    assert again.json()["closed_at"] == closed_payload["closed_at"]
    assert again.json()["close_note"] == "settled"

    summary = client.get("/api/decision-journal/summary").json()
    assert summary["paper_tracked_count"] == 1
    assert summary["closed_count"] == 1


def test_copilot_decision_journal_review_uses_read_only_journal_tool_without_creating_paper_order(
    tmp_path, monkeypatch
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    services = client.app.state.services
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=386.8,
            change_pct=0.3,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6)
        if item.quantity > 0
        else 0.0
        for item in holdings
    }
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        lambda symbol: PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        ),
    )

    draft = client.post(
        "/api/rebalance-drafts", json={"symbol": "AAPL", "target_weight_pct": 15}
    ).json()
    client.post(
        f"/api/rebalance-drafts/{draft['draft_id']}/confirm", json={"note": "ready"}
    )
    review = client.post(
        "/api/pre-trade-reviews", json={"draft_id": draft["draft_id"]}
    ).json()
    client.post("/api/paper-orders", json={"review_id": review["review_id"]})
    entry = client.get("/api/decision-journal").json()["items"][0]
    snapshot = client.post("/api/paper-portfolio/snapshots").json()
    client.post(
        f"/api/decision-journal/{entry['entry_id']}/link-snapshot",
        json={"snapshot_id": snapshot["snapshot_id"]},
    )
    before_counts = {
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }
    before_orders = client.get("/api/paper-orders").json()["items"]

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": "复盘最近一次 AI 调仓建议",
            "page": "holdings",
            "authority_level": "A4",
        },
    ).json()
    assert run["intent"] == "decision_journal_review"
    assert run["skills"] == ["risk-officer"]

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == "list_decision_journal"
    assert events[3]["payload"]["tool"] == "list_decision_journal"
    assert events[3]["payload"]["result"]["count"] >= 1
    assert events[3]["payload"]["result"]["items"][0]["entry_id"] == entry["entry_id"]
    assert client.get("/api/paper-orders").json()["items"] == before_orders
    after_counts = {
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }
    assert after_counts == before_counts

    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [
        (item["tool"], item["status"], item["domain"])
        for item in detail["tool_executions"]
    ] == [("list_decision_journal", "succeeded", "decision-journal")]


def test_copilot_blocks_real_execution_without_team_run_runtime(tmp_path):
    client = make_client(tmp_path)

    denied_by_authority = client.post(
        "/api/copilot/chat",
        json={
            "message": "真实下单买入 AAPL 20 股",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    )
    assert denied_by_authority.status_code == 403
    assert "requires A5" in denied_by_authority.json()["detail"]

    denied_by_disabled_skill = client.post(
        "/api/copilot/chat",
        json={
            "message": "真实下单买入 AAPL 20 股",
            "page": "holdings",
            "symbol": "AAPL",
            "authority_level": "A5",
        },
    )
    assert denied_by_disabled_skill.status_code == 403
    assert "disabled" in denied_by_disabled_skill.json()["detail"]

    assert client.get("/api/team-runs").status_code == 404
    assert client.get("/api/teamrun").status_code == 404


def test_settings_do_not_expose_team_run_runtime(tmp_path):
    client = make_client(tmp_path)
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    body = json.dumps(settings.json(), ensure_ascii=False)
    assert "TeamRun" not in body
    assert "team_run" not in body
    assert "team-runs" not in body
    assert "execution-agent-disabled" in body
    assert "client_capabilities" in body
    assert "thinking_enabled" in body
    assert "risk_policy" in body


def test_settings_runtime_exposes_embedded_runtime_fields(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKBENCH_AI_API_KEY", raising=False)

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def stream(self, **kwargs):
            return iter(())

        def chat(self):
            return None

        def list_models(self):
            return []

    deerflow_pkg = ModuleType("deerflow")
    client_mod = ModuleType("deerflow.client")
    client_mod.DeerFlowClient = FakeClient
    monkeypatch.setitem(sys.modules, "deerflow", deerflow_pkg)
    monkeypatch.setitem(sys.modules, "deerflow.client", client_mod)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "embedded")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODEL_NAME", "demo-model")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_CONFIG_PATH", "/tmp/deerflow.toml")
    monkeypatch.setenv("WORKBENCH_DEERFLOW_THINKING_ENABLED", "false")

    client = make_client(tmp_path)
    runtime = client.get("/api/settings").json()["agent_runtime"]
    assert runtime["mode"] == "embedded"
    assert runtime["active_client"] == "embedded"
    assert runtime["client_capabilities"] == ["stream", "chat", "list_models"]
    assert runtime["config_path"] == "/tmp/deerflow.toml"
    assert runtime["model_name"] == "demo-model"
    assert runtime["thinking_enabled"] is False


def test_settings_runtime_config_roundtrip_and_runtime_metrics_routes(
    tmp_path, monkeypatch
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)

    current = client.get("/api/settings").json()
    assert current["runtime_config"]["runtime_mode"] == "embedded"

    updated = {
        "config": {
            "runtime_mode": "embedded",
            "config_path": "/tmp/runtime.toml",
            "model_name": "demo-embedded-model",
            "thinking_enabled": False,
            "request_timeout_seconds": 45,
            "stream_timeout_seconds": 150,
            "fallback_policy": "direct_on_failure",
            "enable_usage_tracking": True,
            "enable_provider_logging": True,
            "enable_copilot_logging": True,
        }
    }
    assert client.put("/api/settings/runtime", json=updated).json() == updated

    refreshed = client.get("/api/settings").json()
    assert refreshed["runtime_config"]["model_name"] == "demo-embedded-model"
    assert refreshed["runtime_config"]["request_timeout_seconds"] == 45

    client.get("/api/overview")
    metrics = client.get("/api/runtime/metrics")
    assert metrics.status_code == 200
    metrics_payload = metrics.json()
    assert metrics_payload["payload"]["provider"]["total_calls"] >= 1

    provider_events = client.get("/api/runtime/provider-events")
    assert provider_events.status_code == 200
    assert provider_events.json()["items"]

    copilot_runs = client.get("/api/runtime/copilot-runs")
    assert copilot_runs.status_code == 200
    assert isinstance(copilot_runs.json()["items"], list)


def test_settings_expose_tool_bridge_registry_without_enabling_real_orders(tmp_path):
    client = make_client(tmp_path)
    settings = client.get("/api/settings").json()
    tools = {item["name"]: item for item in settings["tools"]}
    fallback_tools = {item["name"]: item for item in DEFAULT_TOOLS}

    assert set(tools) == {
        "get_stock_context",
        "get_daily_history",
        "search_stock_intel",
        "get_portfolio_snapshot",
        "get_active_risk_policy",
        "list_risk_policies",
        "evaluate_policy_risk",
        "analyze_portfolio_risk",
        "list_rebalance_drafts",
        "get_rebalance_draft",
        "create_pre_trade_review",
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
        "get_monitor_events",
        "get_monitor_rules",
        "evaluate_monitor_rules",
        "list_strategies",
        "run_strategy_backtest",
        "get_backtest_result",
        "list_report_templates",
        "generate_report",
        "get_report_quality",
        "generate_draft_order",
        "confirm_rebalance_draft",
        "reject_rebalance_draft",
        "add_watchlist_item",
        "remove_watchlist_item",
        "upsert_holding",
        "dismiss_inbox_item",
        "snooze_inbox_item",
        "mark_inbox_item_done",
        "place_real_order",
    }
    assert "list_rebalance_drafts" in fallback_tools
    assert "get_rebalance_draft" in fallback_tools
    assert "create_pre_trade_review" in fallback_tools
    assert "list_pre_trade_reviews" in fallback_tools
    assert "list_paper_orders" in fallback_tools
    assert "get_paper_portfolio" in fallback_tools
    assert "analyze_paper_performance" in fallback_tools
    assert "create_paper_portfolio_snapshot" in fallback_tools
    assert "list_decision_journal" in fallback_tools
    assert "get_decision_journal_entry" in fallback_tools
    assert "summarize_decision_outcomes" in fallback_tools
    assert "list_review_inbox" in fallback_tools
    assert "summarize_review_inbox" in fallback_tools
    assert "create_paper_order" not in fallback_tools
    assert tools["place_real_order"]["status"] == "blocked"
    assert tools["place_real_order"]["risk"] == "blocked"
    assert settings["risk_policy"]["active"]["policy_id"] == "default-conservative"


def test_review_inbox_api_lists_summarizes_and_updates_overlay_state(tmp_path):
    client = make_client(tmp_path)
    draft = seed_review_inbox_pending_draft(client)
    item_key = f"rebalance_draft:{draft.draft_id}:pending"

    listed = client.get("/api/review-inbox")
    assert listed.status_code == 200
    items = {item["item_key"]: item for item in listed.json()["items"]}
    assert item_key in items
    assert items[item_key]["status"] == "open"

    summary = client.get("/api/review-inbox/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["open_count"] >= 1
    assert payload["high_count"] >= 0
    assert payload["overdue_count"] >= 0
    assert payload["snoozed_count"] == 0

    dismissed = client.post(
        f"/api/review-inbox/{item_key}/dismiss", json={"note": "not now"}
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert all(
        item["item_key"] != item_key
        for item in client.get("/api/review-inbox").json()["items"]
    )

    snoozed_until = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    snoozed = client.post(
        f"/api/review-inbox/{item_key}/snooze",
        json={"snoozed_until": snoozed_until, "note": "later"},
    )
    assert snoozed.status_code == 200
    assert snoozed.json()["status"] == "open"
    summary = client.get("/api/review-inbox/summary").json()
    assert summary["snoozed_count"] == 1

    done = client.post(
        f"/api/review-inbox/{item_key}/mark-done", json={"note": "handled"}
    )
    assert done.status_code == 200
    assert done.json()["status"] == "done"
    assert all(
        item["item_key"] != item_key
        for item in client.get("/api/review-inbox").json()["items"]
    )


def test_review_inbox_api_returns_404_for_unknown_or_non_current_item(tmp_path):
    client = make_client(tmp_path)
    missing = client.post(
        "/api/review-inbox/rebalance_draft:missing:pending/dismiss", json={"note": "x"}
    )
    assert missing.status_code == 404

    services = client.app.state.services
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    old_key = f"rebalance_draft:{draft.draft_id}:pending"
    stale = services.repo.get_rebalance_draft(draft.draft_id)
    stale.valid_until = "2000-01-01T00:00:00+00:00"
    stale.updated_at = "2000-01-01T00:00:00+00:00"
    services.repo.save_rebalance_draft(stale)

    expired = client.get("/api/review-inbox").json()["items"]
    assert any(
        item["item_key"] == f"rebalance_draft:{draft.draft_id}:expired"
        for item in expired
    )
    response = client.post(
        f"/api/review-inbox/{old_key}/mark-done", json={"note": "stale"}
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("今天我需要处理什么？", "summarize_review_inbox"),
        ("列出高优先级待办", "list_review_inbox"),
        ("解释这条待办为什么重要", "list_review_inbox"),
    ],
)
def test_copilot_review_inbox_prompts_use_read_only_inbox_tools_only(
    tmp_path, monkeypatch, message, expected_tool
):
    _force_stub_runtime(monkeypatch)
    client = make_client(tmp_path)
    services = client.app.state.services
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    before_counts = {
        "drafts": len(services.repo.list_rebalance_drafts(limit=None)),
        "reviews": len(services.repo.list_pre_trade_reviews(limit=None)),
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }

    run = client.post(
        "/api/copilot/chat",
        json={
            "message": message,
            "page": "overview",
            "symbol": "AAPL",
            "authority_level": "A4",
        },
    ).json()
    assert run["intent"] == "review_inbox"

    with client.stream("GET", f"/api/copilot/stream/{run['run_id']}") as response:
        events = parse_sse_events("".join(response.iter_text()))

    assert [event["type"] for event in events] == [
        "skill_trace",
        "reasoning",
        "tool_call",
        "tool_result",
        "partial_answer",
        "final",
    ]
    assert events[2]["payload"]["tool"] == expected_tool
    assert events[3]["payload"]["tool"] == expected_tool
    detail = client.get(f"/api/tasks/{run['task_id']}").json()
    assert [
        (item["tool"], item["status"], item["domain"])
        for item in detail["tool_executions"]
    ] == [(expected_tool, "succeeded", "review-inbox")]

    after_counts = {
        "drafts": len(services.repo.list_rebalance_drafts(limit=None)),
        "reviews": len(services.repo.list_pre_trade_reviews(limit=None)),
        "orders": len(services.repo.list_paper_orders(limit=None)),
        "snapshots": len(services.repo.list_paper_portfolio_snapshots(limit=None)),
        "reports": len(services.repo.list_reports(limit=None)),
    }
    assert before_counts == after_counts
    assert services.repo.get_rebalance_draft(draft.draft_id) is not None


def test_settings_tools_registry_cannot_be_overwritten(tmp_path):
    client = make_client(tmp_path)
    payload = {
        "items": [
            {
                "domain": "execution",
                "name": "place_real_order",
                "risk": "low",
                "status": "enabled",
            }
        ]
    }

    response = client.put("/api/settings/tools", json=payload)

    assert response.status_code == 409
    settings = client.get("/api/settings").json()
    tools = {item["name"]: item for item in settings["tools"]}
    assert tools["place_real_order"]["status"] == "blocked"
    assert tools["place_real_order"]["risk"] == "blocked"


def test_closed_loop_smoke_script_runs_and_prints_key_ids(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/closed_loop_smoke.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "risk_decision=" in result.stdout
    assert "draft_id=" in result.stdout
    assert "review_id=" in result.stdout
    assert "paper_order_id=" in result.stdout
    assert "snapshot_id=" in result.stdout
    assert "report_id=" in result.stdout
    assert "journal_entry_id=" in result.stdout
    assert "summary=" in result.stdout


def test_settings_profiles_and_tools_round_trip(tmp_path):
    client = make_client(tmp_path)
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    payload = settings.json()
    assert payload["providers"]
    assert payload["models"]
    assert payload["skills"]
    assert payload["profiles"]
    assert payload["tools"]

    profiles = {
        "items": [
            {
                "name": "测试 Profile",
                "default_model": "gpt-5.4",
                "skills": ["stock-researcher"],
            }
        ]
    }
    assert client.put("/api/settings/profiles", json=profiles).json() == profiles

    updated = client.get("/api/settings").json()
    assert updated["profiles"][0]["name"] == "测试 Profile"
    overview = client.get("/api/overview").json()
    assert overview["audit"][0]["action"] == "settings profiles updated"

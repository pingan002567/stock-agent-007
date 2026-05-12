from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.schemas import AIRunEvaluationCase, AIRunEvaluationResult


def make_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            db_path=tmp_path / "ai-regression.sqlite3", files_root=tmp_path / "files"
        )
    )


def parse_sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for chunk in body.split("\n\n"):
        if not chunk.startswith("event: "):
            continue
        data_line = [line for line in chunk.splitlines() if line.startswith("data: ")][
            0
        ]
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


def run_evaluation_case(
    client: TestClient, case: AIRunEvaluationCase
) -> AIRunEvaluationResult:
    run = client.post(
        "/api/copilot/chat",
        json={
            "message": case.message,
            "page": case.page,
            "symbol": case.symbol,
            "authority_level": case.authority_level.value,
        },
    )
    if run.status_code != 200:
        return AIRunEvaluationResult(
            case_id=case.case_id,
            passed=False,
            notes=[f"chat endpoint returned {run.status_code}"],
        )
    payload = run.json()
    with client.stream("GET", f"/api/copilot/stream/{payload['run_id']}") as response:
        if response.status_code != 200:
            return AIRunEvaluationResult(
                case_id=case.case_id,
                passed=False,
                notes=[f"stream returned {response.status_code}"],
            )
        body = "".join(response.iter_text())

    events = parse_sse_events(body)
    if not events:
        return AIRunEvaluationResult(
            case_id=case.case_id, passed=False, notes=["no SSE events"]
        )

    final = events[-1]
    missing_keys = [k for k in case.min_final_keys if k not in final.get("payload", {})]
    actual_skills = []
    if final.get("payload", {}).get("skill_trace"):
        actual_skills = [item["skill"] for item in final["payload"]["skill_trace"]]
    actual_tools = [
        event["payload"]["tool"] for event in events if event["type"] == "tool_call"
    ]

    notes: list[str] = []
    passed = True

    if final["type"] != "final":
        notes.append(f"last event is '{final['type']}', expected 'final'")
        passed = False
    if missing_keys:
        notes.append(f"missing final keys: {missing_keys}")
        passed = False
    for expected in case.expected_skills:
        if expected not in actual_skills:
            notes.append(f"missing skill: {expected}")
            passed = False
    for expected in case.expected_tools:
        if expected not in actual_tools:
            notes.append(f"missing tool: {expected} (may require real runtime)")
            passed = False

    return AIRunEvaluationResult(
        case_id=case.case_id,
        passed=passed,
        run_id=payload.get("run_id"),
        task_id=payload.get("task_id"),
        final_type=final.get("type"),
        actual_skills=actual_skills,
        actual_tools=actual_tools,
        missing_final_keys=missing_keys,
        notes=notes,
    )


# ── Test cases ──

# risk_scan requires real DeerFlow integration; marked xfail because the
# generated config may not match the installed DeerFlow version.
BASELINE_TOOL_TEST = pytest.param(
    AIRunEvaluationCase(
        case_id="risk_scan",
        message="分析 AAPL 风险",
        page="holdings",
        symbol="AAPL",
        expected_skills=["stock-researcher", "risk-officer", "report-writer"],
        expected_tools=["evaluate_policy_risk"],
        allow_degraded_data=True,
    ),
    marks=pytest.mark.xfail(reason="requires real DeerFlow runtime", strict=False),
    id="risk_scan",
)

# Stub-runtime-safe cases: stub emits only reasoning + final (no tool_calls),
# so they only validate SSE structure and final payload keys.
STRUCTURAL_CASES = [
    AIRunEvaluationCase(
        case_id="monitor_explain",
        message="解释最近一条盯盘事件",
        page="monitor",
    ),
    AIRunEvaluationCase(
        case_id="paper_review",
        message="复盘 paper 调仓效果",
        page="holdings",
    ),
    AIRunEvaluationCase(
        case_id="stock_context",
        message="分析 AAPL 当前情况",
        page="research",
        symbol="AAPL",
    ),
    AIRunEvaluationCase(
        case_id="risk_review",
        message="检查投资组合风险",
        page="holdings",
    ),
    AIRunEvaluationCase(
        case_id="report_write",
        message="生成一份市场复盘报告",
        page="overview",
    ),
    AIRunEvaluationCase(
        case_id="strategy_backtest",
        message="运行策略回测",
        page="strategies",
    ),
    AIRunEvaluationCase(
        case_id="draft_plan",
        message="规划调仓方案",
        page="holdings",
    ),
    AIRunEvaluationCase(
        case_id="decision_review",
        message="复盘最近一次 AI 调仓建议",
        page="holdings",
    ),
]

# Full-coverage cases that require real runtime (tool_call assertions)
FULL_COVERAGE_CASES = [
    BASELINE_TOOL_TEST,
    AIRunEvaluationCase(
        case_id="monitor_explain_tools",
        message="解释最近一条盯盘事件",
        page="monitor",
        expected_tools=["get_monitor_events"],
    ),
    AIRunEvaluationCase(
        case_id="paper_review_tools",
        message="复盘 paper 调仓效果",
        page="holdings",
        expected_tools=["list_paper_orders", "analyze_paper_performance"],
    ),
    AIRunEvaluationCase(
        case_id="stock_context_tools",
        message="分析 AAPL 当前情况",
        page="research",
        symbol="AAPL",
        expected_tools=["get_stock_context"],
    ),
    AIRunEvaluationCase(
        case_id="risk_review_tools",
        message="检查投资组合风险",
        page="holdings",
        expected_tools=["analyze_portfolio_risk", "get_active_risk_policy"],
    ),
    AIRunEvaluationCase(
        case_id="strategy_backtest_tools",
        message="运行策略回测",
        page="strategies",
        expected_tools=["list_strategies"],
    ),
]


# ── Structural tests (work with stub runtime) ──


@pytest.mark.ai_regression
@pytest.mark.parametrize(
    "case", STRUCTURAL_CASES, ids=[c.case_id for c in STRUCTURAL_CASES]
)
def test_sses_structure(tmp_path, case: AIRunEvaluationCase):
    client = make_client(tmp_path)
    result = run_evaluation_case(client, case)
    assert result.passed, "; ".join(result.notes)


# ── Full-coverage tests (require real DeerFlow runtime) ──


@pytest.mark.ai_regression
@pytest.mark.parametrize(
    "case",
    FULL_COVERAGE_CASES,
    ids=lambda c: getattr(c, "case_id", None),
)
def test_full_coverage(tmp_path, case: AIRunEvaluationCase):
    client = make_client(tmp_path)
    result = run_evaluation_case(client, case)
    assert result.passed, "; ".join(result.notes)

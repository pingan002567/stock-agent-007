from __future__ import annotations

import pytest

from backend.agent_runtime.tool_bridge import ToolSpec, WorkbenchToolBridge
from backend.app_services.permission_guard import PermissionDenied
from backend.bootstrap import create_services
from backend.schemas import AuthorityLevel, PriceSnapshot, RebalanceDraftDecisionNoteRequest


@pytest.fixture()
def bridge(tmp_path):
    services = create_services(db_path=tmp_path / "bridge.sqlite3", files_root=tmp_path / "files")
    return WorkbenchToolBridge(
        context_builder=services.context_builder,
        repo=services.repo,
        monitor_service=services.monitor_service,
        strategy_service=services.strategy_service,
        report_service=services.report_service,
        permission_guard=services.permission_guard,
        tool_execution_service=services.tool_execution_service,
    )


def test_tool_bridge_registry_includes_default_tools_and_blocks_real_orders(bridge):
    tools = {tool["name"]: tool for tool in bridge.list_tools()}

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
    assert tools["get_stock_context"]["required_authority"] == "A2"
    assert tools["analyze_portfolio_risk"]["required_authority"] == "A3"
    assert tools["generate_draft_order"]["required_authority"] == "A4"
    assert tools["create_pre_trade_review"]["required_authority"] == "A4"
    assert tools["list_pre_trade_reviews"]["required_authority"] == "A3"
    assert tools["list_paper_orders"]["required_authority"] == "A3"
    assert tools["get_paper_portfolio"]["required_authority"] == "A3"
    assert tools["analyze_paper_performance"]["required_authority"] == "A3"
    assert tools["create_paper_portfolio_snapshot"]["required_authority"] == "A3"
    assert tools["list_decision_journal"]["required_authority"] == "A3"
    assert tools["get_decision_journal_entry"]["required_authority"] == "A3"
    assert tools["summarize_decision_outcomes"]["required_authority"] == "A3"
    assert tools["run_strategy_backtest"]["required_authority"] == "A3"
    assert tools["place_real_order"]["enabled"] is False
    assert tools["place_real_order"]["risk"] == "blocked"
    assert "create_paper_order" not in tools


def test_tool_bridge_lists_and_summarizes_review_inbox_with_ledger(bridge):
    created = bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 15}, AuthorityLevel.A4)
    item_key = f"rebalance_draft:{created['result']['draft_id']}:pending"

    listed = bridge.execute(
        "list_review_inbox",
        {"limit": 10},
        AuthorityLevel.A3,
        run_id="run_inbox",
        task_id="task_inbox",
        call_id="call_list_review_inbox",
        source_mode="stub",
    )
    summary = bridge.execute(
        "summarize_review_inbox",
        {},
        AuthorityLevel.A3,
        run_id="run_inbox",
        task_id="task_inbox",
        call_id="call_summarize_review_inbox",
        source_mode="stub",
    )

    assert any(item["item_key"] == item_key for item in listed["result"]["items"])
    assert summary["result"]["open_count"] >= 1
    executions = bridge.repo.list_tool_executions(task_id="task_inbox")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("list_review_inbox", "review-inbox", "succeeded"),
        ("summarize_review_inbox", "review-inbox", "succeeded"),
    ]


def test_tool_bridge_executes_stock_context_history_intel_and_portfolio_tools(bridge):
    context = bridge.execute("get_stock_context", {"symbol": "AAPL"}, AuthorityLevel.A4)
    assert context["tool"] == "get_stock_context"
    assert context["result"]["symbol"] == "AAPL"
    assert context["evidence_refs"] == ["stock_context", "provider_router"]

    history = bridge.execute("get_daily_history", {"symbol": "AAPL", "days": 3}, AuthorityLevel.A4)
    assert history["result"]["symbol"] == "AAPL"
    assert len(history["result"]["items"]) == 3

    intel = bridge.execute("search_stock_intel", {"symbol": "AAPL"}, AuthorityLevel.A4)
    assert intel["result"]["items"]

    portfolio = bridge.execute("get_portfolio_snapshot", {}, AuthorityLevel.A4)
    assert portfolio["result"]["positions"] >= 1


def test_tool_bridge_analyzes_risk_and_generates_draft_order_without_auto_trade(bridge):
    risk = bridge.execute("analyze_portfolio_risk", {}, AuthorityLevel.A4)
    assert any(item["symbol"] == "AAPL" for item in risk["result"]["risks"])
    assert risk["result"]["risk_policy_ref"]["policy_id"] == "default-conservative"

    draft = bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 15}, AuthorityLevel.A4)
    order = draft["result"]["draft_order"]
    assert draft["tool"] == "generate_draft_order"
    assert draft["result"]["draft_id"].startswith("draft_")
    assert draft["result"]["draft_status"] == "pending_user_confirmation"
    assert order["symbol"] == "AAPL"
    assert order["auto_trade"] is False
    assert order["status"] == "pending_user_confirmation"
    assert "draft_order_guard:auto_trade_false" in draft["evidence_refs"]
    saved = bridge.repo.get_rebalance_draft(draft["result"]["draft_id"])
    assert saved is not None
    assert saved.symbol == "AAPL"


def test_tool_bridge_lists_and_reads_active_risk_policies_with_ledger(bridge):
    active = bridge.execute(
        "get_active_risk_policy",
        {},
        AuthorityLevel.A2,
        run_id="run_policy",
        task_id="task_policy",
        call_id="call_active_policy",
        source_mode="stub",
    )
    listed = bridge.execute(
        "list_risk_policies",
        {},
        AuthorityLevel.A2,
        run_id="run_policy",
        task_id="task_policy",
        call_id="call_list_policies",
        source_mode="stub",
    )
    evaluated = bridge.execute(
        "evaluate_policy_risk",
        {},
        AuthorityLevel.A4,
        run_id="run_policy",
        task_id="task_policy",
        call_id="call_eval_policy",
        source_mode="stub",
    )

    assert active["result"]["policy_id"] == "default-conservative"
    assert listed["result"]["items"][0]["policy_id"] == "default-conservative"
    assert evaluated["result"]["risk_policy_ref"]["policy_id"] == "default-conservative"

    executions = bridge.repo.list_tool_executions(task_id="task_policy")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("get_active_risk_policy", "risk", "succeeded"),
        ("list_risk_policies", "risk", "succeeded"),
        ("evaluate_policy_risk", "risk", "succeeded"),
    ]


def test_tool_bridge_lists_and_gets_rebalance_drafts_with_a4(bridge):
    created = bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 15}, AuthorityLevel.A4)
    draft_id = created["result"]["draft_id"]
    stale = bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 13}, AuthorityLevel.A4)
    stale_id = stale["result"]["draft_id"]
    stale_draft = bridge.repo.get_rebalance_draft(stale_id)
    stale_draft.valid_until = "2000-01-01T00:00:00+00:00"
    stale_draft.updated_at = "2000-01-01T00:00:00+00:00"
    bridge.repo.save_rebalance_draft(stale_draft)

    listed = bridge.execute(
        "list_rebalance_drafts",
        {"symbol": "AAPL", "limit": 10},
        AuthorityLevel.A4,
        run_id="run_draft",
        task_id="task_draft",
        call_id="call_list_drafts",
        source_mode="stub",
    )
    assert listed["result"]["count"] >= 1
    assert any(item["draft_id"] == draft_id for item in listed["result"]["items"])

    expired = bridge.execute(
        "list_rebalance_drafts",
        {"symbol": "AAPL", "status": "expired", "limit": 10},
        AuthorityLevel.A4,
        run_id="run_draft",
        task_id="task_draft",
        call_id="call_list_expired_drafts",
        source_mode="stub",
    )
    assert any(item["draft_id"] == stale_id and item["status"] == "expired" for item in expired["result"]["items"])

    pending = bridge.execute(
        "list_rebalance_drafts",
        {"symbol": "AAPL", "status": "pending_user_confirmation", "limit": 10},
        AuthorityLevel.A4,
        run_id="run_draft",
        task_id="task_draft",
        call_id="call_list_pending_drafts",
        source_mode="stub",
    )
    assert all(item["draft_id"] != stale_id for item in pending["result"]["items"])
    assert all(item["status"] == "pending_user_confirmation" for item in pending["result"]["items"])

    loaded = bridge.execute(
        "get_rebalance_draft",
        {"draft_id": draft_id},
        AuthorityLevel.A4,
        run_id="run_draft",
        task_id="task_draft",
        call_id="call_get_draft",
        source_mode="embedded",
    )
    assert loaded["result"]["draft_id"] == draft_id
    assert loaded["result"]["status"] == "pending_user_confirmation"

    executions = bridge.repo.list_tool_executions(task_id="task_draft")
    assert [(item.tool, item.status, item.domain) for item in executions] == [
        ("list_rebalance_drafts", "succeeded", "planner"),
        ("list_rebalance_drafts", "succeeded", "planner"),
        ("list_rebalance_drafts", "succeeded", "planner"),
        ("get_rebalance_draft", "succeeded", "planner"),
    ]


def test_tool_bridge_creates_and_lists_pre_trade_reviews_and_paper_orders(bridge):
    created = bridge.execute("generate_draft_order", {"symbol": "HK00700", "target_weight_pct": 8}, AuthorityLevel.A4)
    draft_id = created["result"]["draft_id"]
    bridge.rebalance_draft_service.confirm(draft_id, RebalanceDraftDecisionNoteRequest(note="review-ready"))

    review = bridge.execute(
        "create_pre_trade_review",
        {"draft_id": draft_id},
        AuthorityLevel.A4,
        run_id="run_review",
        task_id="task_review",
        call_id="call_create_review",
        source_mode="stub",
    )
    assert review["result"]["review_id"].startswith("review_")
    assert review["result"]["status"] in {"passed", "warning"}
    assert review["result"]["execution_guard"]["auto_trade"] is False

    listed_reviews = bridge.execute(
        "list_pre_trade_reviews",
        {"draft_id": draft_id},
        AuthorityLevel.A3,
        run_id="run_review",
        task_id="task_review",
        call_id="call_list_reviews",
        source_mode="stub",
    )
    assert listed_reviews["result"]["count"] == 1
    assert listed_reviews["result"]["items"][0]["review_id"] == review["result"]["review_id"]

    saved_order = bridge.paper_trading_service.create(review["result"]["review_id"], source_mode="http")
    listed_orders = bridge.execute(
        "list_paper_orders",
        {"review_id": review["result"]["review_id"]},
        AuthorityLevel.A3,
        run_id="run_review",
        task_id="task_review",
        call_id="call_list_orders",
        source_mode="stub",
    )
    assert listed_orders["result"]["count"] == 1
    assert listed_orders["result"]["items"][0]["order_id"] == saved_order.order_id

    executions = bridge.repo.list_tool_executions(task_id="task_review")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("create_pre_trade_review", "planner", "succeeded"),
        ("list_pre_trade_reviews", "planner", "succeeded"),
        ("list_paper_orders", "execution", "succeeded"),
    ]


def test_tool_bridge_create_pre_trade_review_requires_confirmed_draft_id_and_records_failed_ledger(bridge):
    created = bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 15}, AuthorityLevel.A4)
    draft_id = created["result"]["draft_id"]

    with pytest.raises(ValueError, match="draft_id"):
        bridge.execute(
            "create_pre_trade_review",
            {"symbol": "AAPL"},
            AuthorityLevel.A4,
            run_id="run_review_guard",
            task_id="task_review_guard",
            call_id="call_review_missing_draft_id",
            source_mode="stub",
        )

    with pytest.raises(ValueError, match="confirmed_no_execution"):
        bridge.execute(
            "create_pre_trade_review",
            {"draft_id": draft_id},
            AuthorityLevel.A4,
            run_id="run_review_guard",
            task_id="task_review_guard",
            call_id="call_review_pending_draft",
            source_mode="stub",
        )

    executions = bridge.repo.list_tool_executions(task_id="task_review_guard")
    assert [(item.tool, item.status, item.error) for item in executions] == [
        (
            "create_pre_trade_review",
            "failed",
            "create_pre_trade_review requires an explicit confirmed draft_id; symbol-only fallback is disabled",
        ),
        (
            "create_pre_trade_review",
            "failed",
            "draft must be confirmed_no_execution before review, current=pending_user_confirmation",
        ),
    ]


def test_tool_bridge_reads_paper_portfolio_and_creates_snapshot_with_ledger(bridge, monkeypatch):
    holdings = bridge.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
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

    portfolio = bridge.execute(
        "get_paper_portfolio",
        {},
        AuthorityLevel.A3,
        run_id="run_paper",
        task_id="task_paper",
        call_id="call_paper_portfolio",
        source_mode="stub",
    )
    performance = bridge.execute(
        "analyze_paper_performance",
        {},
        AuthorityLevel.A3,
        run_id="run_paper",
        task_id="task_paper",
        call_id="call_paper_performance",
        source_mode="stub",
    )
    snapshot = bridge.execute(
        "create_paper_portfolio_snapshot",
        {},
        AuthorityLevel.A3,
        run_id="run_paper",
        task_id="task_paper",
        call_id="call_paper_snapshot",
        source_mode="stub",
    )

    assert portfolio["result"]["summary"]["baseline_id"].startswith("baseline_")
    assert performance["result"]["since_baseline"]["initial_equity"] > 0
    assert snapshot["result"]["snapshot_id"].startswith("paper_snapshot_")
    assert snapshot["result"]["payload"]["positions"]

    executions = bridge.repo.list_tool_executions(task_id="task_paper")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("get_paper_portfolio", "paper-portfolio", "succeeded"),
        ("analyze_paper_performance", "paper-portfolio", "succeeded"),
        ("create_paper_portfolio_snapshot", "paper-portfolio", "succeeded"),
    ]


def test_tool_bridge_lists_and_summarizes_decision_journal_with_ledger(bridge, monkeypatch):
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
    holdings = bridge.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
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

    draft = bridge.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    bridge.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    review = bridge.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    bridge.paper_trading_service.create(review.review_id, source_mode="http")
    entry = bridge.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry is not None
    snapshot = bridge.paper_portfolio_service.create_snapshot(source_mode="http")
    bridge.decision_journal_service.link_snapshot(entry.entry_id, snapshot.snapshot_id)

    listed = bridge.execute(
        "list_decision_journal",
        {"symbol": "AAPL", "limit": 10},
        AuthorityLevel.A3,
        run_id="run_journal",
        task_id="task_journal",
        call_id="call_list_journal",
        source_mode="stub",
    )
    loaded = bridge.execute(
        "get_decision_journal_entry",
        {"entry_id": entry.entry_id},
        AuthorityLevel.A3,
        run_id="run_journal",
        task_id="task_journal",
        call_id="call_get_journal",
        source_mode="stub",
    )
    summary = bridge.execute(
        "summarize_decision_outcomes",
        {"symbol": "AAPL"},
        AuthorityLevel.A3,
        run_id="run_journal",
        task_id="task_journal",
        call_id="call_summary_journal",
        source_mode="stub",
    )

    assert listed["result"]["count"] == 1
    assert listed["result"]["items"][0]["entry_id"] == entry.entry_id
    assert loaded["result"]["entry_id"] == entry.entry_id
    assert loaded["result"]["chain"]["paper_order"]["review_id"] == review.review_id
    assert summary["result"]["paper_tracked_count"] == 1

    executions = bridge.repo.list_tool_executions(task_id="task_journal")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("list_decision_journal", "decision-journal", "succeeded"),
        ("get_decision_journal_entry", "decision-journal", "succeeded"),
        ("summarize_decision_outcomes", "decision-journal", "succeeded"),
    ]


def test_tool_bridge_lists_strategies_runs_backtests_and_reads_results(bridge):
    listed = bridge.execute("list_strategies", {}, AuthorityLevel.A2)
    assert listed["result"]["items"][0]["strategy_id"] == "concentration-control"

    run = bridge.execute(
        "run_strategy_backtest",
        {"strategy_id": "concentration-control", "period": {"days": 14}, "universe": ["AAPL"]},
        AuthorityLevel.A4,
        run_id="run_strategy",
        task_id="task_strategy",
        call_id="call_backtest",
        source_mode="stub",
    )
    assert run["result"]["strategy_id"] == "concentration-control"
    assert run["result"]["execution_guard"]["auto_trade"] is False

    loaded = bridge.execute(
        "get_backtest_result",
        {"run_id": run["result"]["run_id"]},
        AuthorityLevel.A2,
        run_id="run_strategy",
        task_id="task_strategy",
        call_id="call_get_backtest",
        source_mode="embedded",
    )
    assert loaded["result"]["run_id"] == run["result"]["run_id"]

    executions = bridge.repo.list_tool_executions(task_id="task_strategy")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("run_strategy_backtest", "strategy", "succeeded"),
        ("get_backtest_result", "strategy", "succeeded"),
    ]


def test_tool_bridge_lists_report_templates_generates_report_and_reads_quality(bridge):
    templates = bridge.execute(
        "list_report_templates",
        {},
        AuthorityLevel.A2,
        run_id="run_report",
        task_id="task_report",
        call_id="call_templates",
        source_mode="stub",
    )
    assert {item["report_type"] for item in templates["result"]["items"]} == {
        "stock_research",
        "monitor_review",
        "strategy_backtest",
        "paper_portfolio_review",
    }

    report = bridge.execute(
        "generate_report",
        {"report_type": "stock_research", "source_type": "stock", "source_id": "AAPL"},
        AuthorityLevel.A2,
        run_id="run_report",
        task_id="task_report",
        call_id="call_generate_report",
        source_mode="stub",
    )
    assert report["result"]["report_type"] == "stock_research"
    assert report["result"]["quality_status"] in {"passed", "warning"}

    quality = bridge.execute(
        "get_report_quality",
        {"report_id": report["result"]["report_id"]},
        AuthorityLevel.A2,
        run_id="run_report",
        task_id="task_report",
        call_id="call_report_quality",
        source_mode="stub",
    )
    assert quality["result"]["report_id"] == report["result"]["report_id"]
    assert quality["result"]["latest"]["status"] == report["result"]["quality_status"]

    executions = bridge.repo.list_tool_executions(task_id="task_report")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("list_report_templates", "report", "succeeded"),
        ("generate_report", "report", "succeeded"),
        ("get_report_quality", "report", "succeeded"),
    ]


def test_tool_bridge_generate_report_rejects_template_report_type_mismatch_and_records_failed_ledger(bridge):
    with pytest.raises(ValueError) as exc:
        bridge.execute(
            "generate_report",
            {
                "report_type": "monitor_review",
                "source_type": "stock",
                "source_id": "AAPL",
                "template_id": "stock_research_default",
            },
            AuthorityLevel.A2,
            run_id="run_report_mismatch",
            task_id="task_report_mismatch",
            call_id="call_report_mismatch",
            source_mode="stub",
        )
    assert "template/report_type mismatch" in str(exc.value)

    executions = bridge.repo.list_tool_executions(task_id="task_report_mismatch")
    assert [(item.tool, item.domain, item.status, item.call_id) for item in executions] == [
        ("generate_report", "report", "failed", "call_report_mismatch")
    ]
    assert "template/report_type mismatch" in executions[0].error


def test_tool_bridge_blocks_insufficient_authority_and_real_orders(bridge):
    with pytest.raises(PermissionDenied):
        bridge.execute("generate_draft_order", {"symbol": "AAPL", "target_weight_pct": 15}, AuthorityLevel.A3)

    with pytest.raises(PermissionDenied):
        bridge.execute("list_rebalance_drafts", {}, AuthorityLevel.A3, task_id="task_draft_block")

    with pytest.raises(PermissionDenied) as exc:
        bridge.execute("place_real_order", {"symbol": "AAPL", "quantity": 1}, AuthorityLevel.A5)
    assert "real order execution is disabled" in str(exc.value)

    blocked = bridge.repo.list_tool_executions(task_id="task_draft_block")
    assert [(item.tool, item.status, item.domain) for item in blocked] == [
        ("list_rebalance_drafts", "blocked", "planner")
    ]


def test_tool_bridge_records_tool_execution_outcomes_and_skips_unknown_tools(bridge):
    bridge.tool_execution_service.summary_limit = 18
    bridge._handlers["search_stock_intel"] = lambda arguments: {"blob": "x" * 80}

    bridge.execute(
        "search_stock_intel",
        {"symbol": "AAPL"},
        AuthorityLevel.A4,
        run_id="run_1",
        task_id="task_1",
        call_id="call_success",
        source_mode="stub",
    )

    with pytest.raises(PermissionDenied):
        bridge.execute(
            "place_real_order",
            {"symbol": "AAPL", "quantity": 1},
            AuthorityLevel.A5,
            run_id="run_1",
            task_id="task_1",
            call_id="call_blocked",
            source_mode="embedded",
        )

    original_spec = bridge._specs["search_stock_intel"]
    bridge._specs["failing_tool"] = ToolSpec(
        "failing_tool",
        original_spec.domain,
        original_spec.required_authority,
        original_spec.risk,
        original_spec.enabled,
        original_spec.input_schema,
        original_spec.evidence_refs,
    )
    bridge._handlers["failing_tool"] = lambda arguments: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        bridge.execute(
            "failing_tool",
            {"symbol": "AAPL"},
            AuthorityLevel.A4,
            run_id="run_1",
            task_id="task_1",
            call_id="call_failed",
            source_mode="embedded",
        )

    with pytest.raises(KeyError):
        bridge.execute("missing_tool", {}, AuthorityLevel.A4, task_id="task_1")

    executions = bridge.repo.list_tool_executions(task_id="task_1")
    assert [(item.tool, item.status, item.call_id, item.source_mode) for item in executions] == [
        ("search_stock_intel", "succeeded", "call_success", "stub"),
        ("place_real_order", "blocked", "call_blocked", "embedded"),
        ("failing_tool", "failed", "call_failed", "embedded"),
    ]
    assert executions[0].run_id == "run_1"
    assert executions[0].domain == "intel"
    assert executions[0].authority_level == "A2"
    assert executions[0].arguments == {"symbol": "AAPL"}
    assert executions[0].result_summary.endswith("…")
    assert len(executions[0].result_summary) == 18
    assert executions[1].domain == "execution"
    assert executions[1].arguments == {"symbol": "AAPL", "quantity": 1}
    assert executions[1].error and "real order execution is disabled" in executions[1].error
    assert executions[2].error == "boom"


def test_tool_bridge_executes_monitor_tools_and_records_monitor_ledger(bridge):
    bridge.repo.save_monitor_status(
        bridge.monitor_service.get_status().model_copy(update={"status": "running"})
    )
    bridge.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})

    events = bridge.execute(
        "get_monitor_events",
        {"limit": 5},
        AuthorityLevel.A2,
        run_id="run_monitor",
        task_id="task_monitor",
        call_id="call_monitor_events",
        source_mode="stub",
    )
    rules = bridge.execute(
        "get_monitor_rules",
        {},
        AuthorityLevel.A2,
        run_id="run_monitor",
        task_id="task_monitor",
        call_id="call_monitor_rules",
        source_mode="stub",
    )
    evaluation = bridge.execute(
        "evaluate_monitor_rules",
        {"source": "tool", "force": True},
        AuthorityLevel.A2,
        run_id="run_monitor",
        task_id="task_monitor",
        call_id="call_monitor_eval",
        source_mode="stub",
    )

    assert events["tool"] == "get_monitor_events"
    assert "items" in events["result"]
    assert rules["result"]["items"]
    assert evaluation["result"]["created"] >= 1

    executions = bridge.repo.list_tool_executions(task_id="task_monitor")
    assert [(item.tool, item.domain, item.status) for item in executions] == [
        ("get_monitor_events", "monitor", "succeeded"),
        ("get_monitor_rules", "monitor", "succeeded"),
        ("evaluate_monitor_rules", "monitor", "succeeded"),
    ]


def test_tool_bridge_monitor_events_explanation_matches_returned_event(bridge):
    fallback = bridge.execute("get_monitor_events", {"symbol": "HK00700", "limit": 1}, AuthorityLevel.A2)
    assert fallback["result"]["items"][0]["symbol"] == "HK00700"
    assert fallback["result"]["explanation"]["event"]["event_id"] == fallback["result"]["items"][0]["event_id"]

    bridge.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})
    bridge.monitor_service.evaluate_once(source="manual")

    miss = bridge.execute("get_monitor_events", {"symbol": "MSFT", "limit": 1}, AuthorityLevel.A2)
    assert miss["result"]["items"] == []
    assert miss["result"]["explanation"]["event"] is None

    hit = bridge.execute("get_monitor_events", {"symbol": "AAPL", "limit": 1}, AuthorityLevel.A2)
    assert hit["result"]["items"][0]["symbol"] == "AAPL"
    assert hit["result"]["explanation"]["event"]["event_id"] == hit["result"]["items"][0]["event_id"]

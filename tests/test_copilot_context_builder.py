from __future__ import annotations

from backend.bootstrap import create_services
from backend.schemas import HoldingPosition, WatchlistItem


def _make_services(tmp_path):
    return create_services(db_path=tmp_path / "context.sqlite3", files_root=tmp_path / "files")


def test_build_overview_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="overview", symbol=None)

    assert ctx["page"] == "overview"
    assert "symbol_summary" not in ctx
    assert "overview" in ctx
    overview = ctx["overview"]
    assert "active_risk_policy" in overview
    assert overview["active_risk_policy"]["policy_id"] == "default-conservative"
    assert "holdings" in overview
    assert overview["holdings"]["position_count"] >= 1
    assert "monitor" in overview
    assert "reports" in overview
    assert "tasks" in overview
    assert "inbox" in overview


def test_build_with_symbol_includes_summary(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="holdings", symbol="AAPL")

    assert ctx["page"] == "holdings"
    assert "symbol_summary" in ctx
    summary = ctx["symbol_summary"]
    assert summary["symbol"] == "AAPL"
    assert summary["name"] == "Apple"
    assert "price" in summary
    assert summary["price"]["last"] > 0
    assert "relation" in summary
    assert "holding" in summary
    assert "ai_state" in summary
    assert "latest_report" in summary


def test_build_holdings_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="holdings")

    assert ctx["page"] == "holdings"
    assert "holdings" in ctx
    holdings = ctx["holdings"]
    assert holdings["position_count"] >= 1
    assert holdings["market_value_total"] > 0
    assert len(holdings["top_positions"]) <= 3


def test_build_monitor_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="monitor")

    assert ctx["page"] == "monitor"
    assert "monitor" in ctx
    monitor = ctx["monitor"]
    assert "status" in monitor
    assert "items" in monitor


def test_build_reports_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="reports")

    assert ctx["page"] == "reports"
    assert "reports" in ctx
    assert len(ctx["reports"]["items"]) <= 5


def test_build_tasks_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="tasks")

    assert ctx["page"] == "tasks"
    assert "tasks" in ctx
    assert len(ctx["tasks"]["items"]) <= 5


def test_build_stock_page_empty(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="stock", symbol=None)

    assert ctx["page"] == "stock"
    assert "symbol_summary" not in ctx


def test_build_journal_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="journal")

    assert ctx["page"] == "journal"
    assert "journal" in ctx
    assert len(ctx["journal"]["items"]) <= 5


def test_build_inbox_page(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="inbox")

    assert ctx["page"] == "inbox"
    assert "inbox" in ctx
    inbox = ctx["inbox"]
    assert "summary" in inbox
    assert "items" in inbox


def test_unknown_page_falls_back_to_overview(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="nonexistent")

    assert ctx["page"] == "overview"
    assert "overview" in ctx


def test_empty_page_falls_back_to_overview(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="")

    assert ctx["page"] == "overview"


def test_holdings_summary_top_positions_truncated_to_3(tmp_path):
    services = _make_services(tmp_path)
    services.repo.upsert_holding(HoldingPosition(symbol="MSFT", name="Microsoft", quantity=10, market_value=400000, weight_pct=15.0))
    services.repo.upsert_holding(HoldingPosition(symbol="GOOGL", name="Alphabet", quantity=5, market_value=350000, weight_pct=12.0))
    services.repo.upsert_holding(HoldingPosition(symbol="TSLA", name="Tesla", quantity=10, market_value=200000, weight_pct=8.0))
    services.repo.upsert_holding(HoldingPosition(symbol="NVDA", name="NVIDIA", quantity=3, market_value=180000, weight_pct=6.0))

    ctx = services.copilot_context_builder.build(page="holdings")
    assert len(ctx["holdings"]["top_positions"]) <= 3


def test_symbol_summary_includes_watchlist_and_holding_relation(tmp_path):
    services = _make_services(tmp_path)
    services.repo.upsert_watchlist_item(WatchlistItem(symbol="AAPL", name="Apple", group="核心持仓", monitored=True))

    ctx = services.copilot_context_builder.build(page="stock", symbol="AAPL")
    rel = ctx["symbol_summary"]["relation"]
    assert rel["in_watchlist"] is True
    assert rel["in_holdings"] is True
    assert rel["monitored"] is True


def test_symbol_summary_ai_state(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="stock", symbol="600519")
    ai_state = ctx["symbol_summary"]["ai_state"]

    assert "score" in ai_state
    assert "risk_label" in ai_state
    assert "stance" in ai_state
    assert "confidence" in ai_state


def test_reports_summary_respects_limit(tmp_path):
    services = _make_services(tmp_path)
    from backend.schemas import ReportGenerateRequest

    for _ in range(3):
        services.report_service.generate(
            ReportGenerateRequest(report_type="stock_research", source_type="stock", source_id="AAPL")
        )

    ctx = services.copilot_context_builder.build(page="reports")
    assert len(ctx["reports"]["items"]) <= 5


def test_monitor_summary_includes_status_and_events(tmp_path):
    services = _make_services(tmp_path)
    services.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})
    services.monitor_service.evaluate_once(source="manual", force=True)

    ctx = services.copilot_context_builder.build(page="monitor")
    monitor = ctx["monitor"]
    assert "status" in monitor
    assert monitor["status"]["status"] in {"running", "paused", "stopped"}
    assert "items" in monitor

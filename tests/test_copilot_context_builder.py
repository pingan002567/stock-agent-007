from __future__ import annotations

from backend.bootstrap import create_services
from backend.schemas import HoldingPosition, PriceSnapshot, WatchlistItem


def _make_services(tmp_path):
    return create_services(db_path=tmp_path / "context.sqlite3", files_root=tmp_path / "files")


def test_build_returns_page_only_without_prefetch_dumps(tmp_path):
    services = _make_services(tmp_path)
    for page in ("overview", "holdings", "monitor", "reports", "tasks", "journal", "inbox", "chat"):
        ctx = services.copilot_context_builder.build(page=page, symbol=None)
        assert ctx == {"page": page}


def test_copilot_chat_context_keeps_symbol_anchor(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="chat", symbol="600519", intent="copilot_chat")
    assert "symbol_summary" in ctx
    assert ctx["page"] == "chat"
    assert set(ctx) <= {"page", "symbol_summary"}


def test_build_with_symbol_includes_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app_services.context_builder.get_realtime_quote",
        lambda symbol: PriceSnapshot(
            last=193.7, change_pct=1.2, updated_at="2026-01-01T00:00:00+00:00", source="test"
        ),
    )
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


def test_build_stock_page_empty(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="stock", symbol=None)
    assert ctx["page"] == "stock"
    assert "symbol_summary" not in ctx


def test_unknown_symbol_does_not_crash_build(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="chat", symbol="药明")
    assert ctx["page"] == "chat"
    assert ctx["symbol_summary"]["symbol"] == "药明"
    assert ctx["symbol_summary"]["status"] == "unavailable"


def test_unknown_page_falls_back_to_overview(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="nonexistent")
    assert ctx["page"] == "overview"


def test_empty_page_falls_back_to_overview(tmp_path):
    services = _make_services(tmp_path)
    ctx = services.copilot_context_builder.build(page="")
    assert ctx["page"] == "overview"


def test_symbol_summary_includes_watchlist_and_holding_relation(tmp_path):
    services = _make_services(tmp_path)
    services.repo.upsert_watchlist_item(WatchlistItem(symbol="AAPL", name="Apple", group="核心持仓", monitored=True))
    services.repo.upsert_holding(HoldingPosition(symbol="AAPL", name="Apple", quantity=1, market_value=100, weight_pct=10))

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


def test_holdings_summary_helper_still_truncates_top_positions(tmp_path):
    services = _make_services(tmp_path)
    services.repo.upsert_holding(HoldingPosition(symbol="MSFT", name="Microsoft", quantity=10, market_value=400000, weight_pct=15.0))
    services.repo.upsert_holding(HoldingPosition(symbol="GOOGL", name="Alphabet", quantity=5, market_value=350000, weight_pct=12.0))
    services.repo.upsert_holding(HoldingPosition(symbol="TSLA", name="Tesla", quantity=10, market_value=200000, weight_pct=8.0))
    services.repo.upsert_holding(HoldingPosition(symbol="NVDA", name="NVIDIA", quantity=3, market_value=180000, weight_pct=6.0))

    summary = services.copilot_context_builder._holdings_summary()
    assert len(summary["top_positions"]) <= 3

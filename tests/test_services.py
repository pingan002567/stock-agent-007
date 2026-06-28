from __future__ import annotations

import asyncio
from datetime import datetime
import json

import pytest
from pydantic import ValidationError

from backend.app_services.permission_guard import PermissionDenied
from backend.agent_runtime.deerflow_client import DeerFlowClientAdapter
from backend.agent_runtime.prompt_envelope import build_prompt_envelope
from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
from backend.bootstrap import create_services
from backend.schemas import (
    AuthorityLevel,
    CopilotRequest,
    HoldingPosition,
    PaperOrder,
    PaperOrderCancelRequest,
    PaperOrderStatus,
    PriceSnapshot,
    PreTradeReviewStatus,
    RebalanceDraftDecisionNoteRequest,
    ReportGenerateRequest,
    RiskPolicy,
    RiskPolicyRef,
    RiskPolicyRules,
    StrategySpec,
    WatchlistItem,
)
from backend.stock_domain.catalog import search_stocks
from backend.stock_domain.provider_router import ProviderRouter
from backend.stock_domain.providers import AkShareMarketDataProvider, MockMarketDataProvider, ProviderError
from backend.stock_domain.risk_tools import analyze_portfolio_risk

CANONICAL_EXECUTION_GUARD = {
    "auto_trade": False,
    "place_real_order_enabled": False,
    "paper_trading": "sandbox_only",
    "real_order": "blocked",
}


@pytest.fixture()
def services(tmp_path):
    return create_services(db_path=tmp_path / "workbench.sqlite3", files_root=tmp_path / "files")


def test_stock_search_supports_symbol_name_and_alias():
    assert search_stocks("AAPL")[0]["name"] == "Apple"
    assert search_stocks("腾讯")[0]["symbol"] == "HK00700"
    assert search_stocks("maotai")[0]["symbol"] == "600519"


def test_watchlist_to_stock_context(services):
    services.repo.upsert_watchlist_item(WatchlistItem(symbol="AAPL", name="Apple", group="核心持仓", monitored=True))
    context = services.context_builder.build_stock_context("apple")
    assert context.symbol == "AAPL"
    assert context.relation.in_watchlist is True
    assert context.relation.in_holdings is True
    assert context.relation.monitored is True


def test_holdings_risk_flags_concentration(services):
    risk = analyze_portfolio_risk(services.repo.list_holdings())
    assert risk["risk_count"] >= 1
    assert any(item["symbol"] == "AAPL" for item in risk["risks"])


def test_risk_policy_service_seeds_default_active_policy(services):
    policy = services.risk_policy_service.get_active_policy()
    assert policy.policy_id == "default-conservative"
    assert policy.is_active is True
    assert policy.is_default is True
    assert policy.rules.single_position_max_weight_pct == 15
    assert policy.rules.single_position_warning_weight_pct == 12
    assert policy.rules.sector_max_weight_pct == 35


def test_research_task_creates_report_and_audit(services):
    context = services.context_builder.build_stock_context("600519")
    task = services.task_service.create("600519 深研", "stock-researcher", "read_quote")
    report = services.report_service.create_stock_report(context)
    services.audit_service.record("stock research created", f"{task.task_id} {report.report_id}")
    assert services.repo.get_task(task.task_id).status == "running"
    assert services.repo.get_report(report.report_id).symbol == "600519"
    assert services.repo.list_audit()[0].action == "stock research created"


def test_report_service_templates_generate_and_rerun_quality(services):
    templates = services.report_service.list_templates()
    assert {item.report_type for item in templates} == {
        "stock_research",
        "monitor_review",
        "strategy_backtest",
        "paper_portfolio_review",
    }

    report = services.report_service.generate(
        ReportGenerateRequest(report_type="stock_research", source_type="stock", source_id="AAPL")
    )
    assert report.quality_status in {"passed", "warning"}
    assert services.repo.get_latest_report_quality_check(report.report_id).status == report.quality_status

    rerun = services.report_service.rerun_quality(report.report_id)
    assert rerun["quality_status"] == report.quality_status
    assert len(services.repo.list_report_quality_checks(report.report_id)) == 2


def test_import_holding_updates_context(services):
    services.repo.upsert_holding(HoldingPosition(symbol="AAPL", name="Apple", quantity=10, market_value=1937, weight_pct=9.5))
    context = services.context_builder.build_stock_context("AAPL")
    assert context.holding.quantity == 10
    assert context.holding.weight_pct == 9.5


def test_rebalance_draft_service_lifecycle_without_real_execution(services):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15},
        source_mode="http",
    )
    assert draft.status.value == "pending_user_confirmation"
    assert draft.auto_trade is False
    assert draft.risk_policy_ref and draft.risk_policy_ref.policy_id == "default-conservative"
    assert draft.validity_source == "risk_policy.rules.draft_valid_hours"
    assert draft.output["execution_guard"] == CANONICAL_EXECUTION_GUARD

    confirmed = services.rebalance_draft_service.confirm(
        draft.draft_id,
        RebalanceDraftDecisionNoteRequest(note="人工确认，仅保留审计"),
    )
    assert confirmed.status.value == "confirmed_no_execution"
    assert confirmed.note == "人工确认，仅保留审计"
    assert confirmed.output["execution_guard"] == CANONICAL_EXECUTION_GUARD
    assert services.repo.get_rebalance_draft(draft.draft_id).status.value == "confirmed_no_execution"


def test_rebalance_draft_auto_creates_decision_journal_entry(services):
    draft = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")

    entry = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)

    assert entry is not None
    assert entry.draft_id == draft.draft_id
    assert entry.symbol == "AAPL"
    assert entry.status == "open"
    assert entry.source_type == "rebalance_draft"


def test_rebalance_draft_valid_until_comes_from_active_policy(services):
    updated = services.risk_policy_service.update_policy(
        "default-conservative",
        services.risk_policy_service.get_active_policy().model_copy(
            update={
                "rules": services.risk_policy_service.get_active_policy().rules.model_copy(update={"draft_valid_hours": 6})
            }
        ),
    )
    services.risk_policy_service.activate_policy(updated.policy_id)

    draft = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    delta_hours = (
        datetime.fromisoformat(draft.valid_until) - datetime.fromisoformat(draft.created_at)
    ).total_seconds() / 3600
    assert 5.9 <= delta_hours <= 6.1


def test_pre_trade_review_service_passes_and_paper_trading_fills_without_touching_holdings(monkeypatch, services):
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
    before = [(item.symbol, item.quantity, item.market_value, item.weight_pct) for item in services.repo.list_holdings()]
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    assert draft.output["execution_guard"] == CANONICAL_EXECUTION_GUARD
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))

    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    assert review.status == PreTradeReviewStatus.PASSED
    assert review.execution_guard == CANONICAL_EXECUTION_GUARD

    entry_after_review = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry_after_review is not None
    assert entry_after_review.review_id == review.review_id
    assert entry_after_review.status == "reviewed"

    order = services.paper_trading_service.create(review.review_id, source_mode="http")
    assert order.status.value == "paper_filled"
    assert order.side == "SELL"
    assert order.execution_guard == CANONICAL_EXECUTION_GUARD

    entry_after_order = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry_after_order is not None
    assert entry_after_order.paper_order_id == order.order_id
    assert entry_after_order.status == "paper_tracked"

    cancelled = services.paper_trading_service.cancel(order.order_id, PaperOrderCancelRequest(note="sandbox rollback"))
    assert cancelled.status.value == "paper_cancelled"
    after = [(item.symbol, item.quantity, item.market_value, item.weight_pct) for item in services.repo.list_holdings()]
    assert after == before


def test_pre_trade_review_service_blocks_policy_mismatch_and_paper_order(services):
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    services.risk_policy_service.update_policy(
        "default-conservative",
        services.risk_policy_service.get_active_policy().model_copy(
            update={
                "rules": services.risk_policy_service.get_active_policy().rules.model_copy(
                    update={"single_position_max_weight_pct": 16}
                )
            }
        ),
    )

    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    assert review.status == PreTradeReviewStatus.BLOCKED
    assert "risk_policy_ref_mismatch" in review.blocker_codes

    with pytest.raises(ValueError):
        services.paper_trading_service.create(review.review_id, source_mode="http")


@pytest.mark.parametrize(
    ("mutate_ref", "expected_ref", "expected_blocker"),
    [
        (
            lambda ref: ref.model_copy(update={"policy_id": "default-conservative-stale"}),
            lambda active: {"policy_id": active.policy_id, "version": active.version, "updated_at": active.updated_at},
            "risk_policy_ref_not_found",
        ),
        (
            lambda ref: ref.model_copy(update={"version": ref.version + 1}),
            lambda active: {"policy_id": active.policy_id, "version": active.version, "updated_at": active.updated_at},
            "risk_policy_ref_mismatch",
        ),
        (
            lambda ref: ref.model_copy(update={"updated_at": "2000-01-01T00:00:00+00:00"}),
            lambda active: {"policy_id": active.policy_id, "version": active.version, "updated_at": active.updated_at},
            "risk_policy_ref_mismatch",
        ),
    ],
)
def test_pre_trade_review_service_blocks_when_any_risk_policy_ref_field_drifts(
    services, mutate_ref, expected_ref, expected_blocker
):
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))

    saved = services.repo.get_rebalance_draft(draft.draft_id)
    assert saved and saved.risk_policy_ref is not None
    saved.risk_policy_ref = RiskPolicyRef.model_validate(mutate_ref(saved.risk_policy_ref))
    services.repo.save_rebalance_draft(saved)

    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    active = services.risk_policy_service.get_active_policy()

    assert review.status == PreTradeReviewStatus.BLOCKED
    assert review.risk_policy_ref is not None
    assert expected_blocker in review.blocker_codes
    assert review.risk_policy_ref.model_dump(include={"policy_id", "version", "updated_at"}) != expected_ref(active)

    with pytest.raises(ValueError):
        services.paper_trading_service.create(review.review_id, source_mode="http")


def test_paper_trading_keeps_degraded_quote_metadata(monkeypatch, services):
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
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))

    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    assert review.status == PreTradeReviewStatus.WARNING
    assert review.degraded is True
    assert review.execution_guard == CANONICAL_EXECUTION_GUARD

    order = services.paper_trading_service.create(review.review_id, source_mode="http")
    assert order.status.value == "paper_filled"
    assert order.quote_degraded is True
    assert order.quote_degraded_reason == "primary feed unavailable"


def test_paper_portfolio_baseline_mirrors_current_holdings_and_does_not_drift(monkeypatch, services):
    holdings = services.repo.list_holdings()
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

    projection = services.paper_portfolio_service.get_projection()
    baseline = services.paper_portfolio_service.get_baseline()
    baseline_positions = {item.symbol: item for item in baseline.positions}

    assert baseline.initial_cash == 0
    assert baseline.initial_nav == pytest.approx(sum(item.market_value for item in holdings))
    assert {item.symbol for item in baseline.positions} == {item.symbol for item in holdings}
    assert projection.order_count == 0
    assert {item.symbol: item.market_value for item in projection.positions} == {
        item.symbol: pytest.approx(item.market_value) for item in holdings
    }

    services.repo.upsert_holding(
        HoldingPosition(symbol="AAPL", name="Apple", quantity=1, market_value=1, weight_pct=0.1)
    )
    drifted = services.paper_portfolio_service.get_projection()
    aapl = next(item for item in drifted.positions if item.symbol == "AAPL")

    assert aapl.quantity == pytest.approx(baseline_positions["AAPL"].quantity)
    assert aapl.market_value == pytest.approx(baseline_positions["AAPL"].baseline_market_value)
    assert services.repo.get_config("paper_portfolio_baseline")["baseline_id"] == baseline.baseline_id


def test_paper_portfolio_projection_excludes_non_filled_orders_and_clamps_sell_without_short(monkeypatch, services):
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
        for item in holdings
    }
    prices["MSFT"] = 100.0
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

    baseline = services.paper_portfolio_service.get_baseline()
    aapl_qty = next(item.quantity for item in baseline.positions if item.symbol == "AAPL")
    ref = RiskPolicyRef(
        policy_id="default-conservative",
        name="Default Conservative",
        version=1,
        updated_at="2026-05-13T00:00:00+00:00",
    )
    for order in [
        PaperOrder(
            order_id="paper_buy_msft",
            review_id="review_msft",
            source_draft_id="draft_msft",
            status=PaperOrderStatus.PAPER_FILLED,
            symbol="MSFT",
            side="BUY",
            target_weight_pct=5,
            delta_weight_pct=5,
            paper_price=100,
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:00:00+00:00",
            paper_quantity_estimate=10,
            paper_notional_estimate=1000,
            risk_policy_ref=ref,
            filled_at="2026-05-13T08:01:00+00:00",
            created_at="2026-05-13T08:01:00+00:00",
        ),
        PaperOrder(
            order_id="paper_sell_aapl_clamped",
            review_id="review_aapl",
            source_draft_id="draft_aapl",
            status=PaperOrderStatus.PAPER_FILLED,
            symbol="AAPL",
            side="SELL",
            target_weight_pct=0,
            delta_weight_pct=-25,
            paper_price=prices["AAPL"],
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:02:00+00:00",
            paper_quantity_estimate=aapl_qty + 10,
            paper_notional_estimate=(aapl_qty + 10) * prices["AAPL"],
            risk_policy_ref=ref,
            filled_at="2026-05-13T08:02:00+00:00",
            created_at="2026-05-13T08:02:00+00:00",
        ),
        PaperOrder(
            order_id="paper_cancelled_ignored",
            review_id="review_cancelled",
            source_draft_id="draft_cancelled",
            status=PaperOrderStatus.PAPER_CANCELLED,
            symbol="TSLA",
            side="BUY",
            target_weight_pct=4,
            delta_weight_pct=4,
            paper_price=200,
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:03:00+00:00",
            paper_quantity_estimate=5,
            paper_notional_estimate=1000,
        ),
        PaperOrder(
            order_id="paper_rejected_ignored",
            review_id="review_rejected",
            source_draft_id="draft_rejected",
            status=PaperOrderStatus.PAPER_REJECTED,
            symbol="NVDA",
            side="BUY",
            target_weight_pct=4,
            delta_weight_pct=4,
            paper_price=100,
            paper_price_source="mock_adapter",
            paper_price_updated_at="2026-05-13T08:04:00+00:00",
            paper_quantity_estimate=5,
            paper_notional_estimate=500,
        ),
    ]:
        services.repo.save_paper_order(order)

    projection = services.paper_portfolio_service.get_projection()
    symbols = {item.symbol for item in projection.positions}

    assert "MSFT" in symbols
    assert "TSLA" not in symbols
    assert "NVDA" not in symbols
    assert "AAPL" not in symbols
    assert projection.order_count == 2
    assert any(item.code == "sell_clamped_no_short" and item.symbol == "AAPL" for item in projection.warnings)
    assert projection.latest_risk_policy_ref and projection.latest_risk_policy_ref.policy_id == "default-conservative"
    assert projection.risk_policy_refs[0].policy_id == "default-conservative"


def test_paper_portfolio_performance_and_snapshot_keep_degraded_quote_metadata(monkeypatch, services):
    holdings = services.repo.list_holdings()
    prices = {
        item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
        for item in holdings
    }

    def fake_quote(symbol: str) -> PriceSnapshot:
        degraded = symbol.upper() == "AAPL"
        return PriceSnapshot(
            last=prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=degraded,
            degraded_reason="primary feed unavailable" if degraded else None,
        )

    monkeypatch.setattr("backend.app_services.paper_portfolio_service.provider_router.get_quote", fake_quote)

    projection = services.paper_portfolio_service.get_projection()
    performance = services.paper_portfolio_service.get_performance()
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")

    assert projection.degraded is True
    assert performance["degraded"] is True
    assert performance["quotes"]["AAPL"]["degraded"] is True
    assert performance["quotes"]["AAPL"]["degraded_reason"] == "primary feed unavailable"
    assert snapshot.payload["degraded"] is True
    assert snapshot.payload["quotes"]["AAPL"]["degraded"] is True
    assert snapshot.payload["positions"]
    assert services.repo.list_audit()[0].action == "paper portfolio snapshot created"


def test_paper_portfolio_review_report_reads_snapshot_payload_without_live_quote(monkeypatch, services):
    holdings = services.repo.list_holdings()
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
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    monkeypatch.setattr(
        "backend.stock_domain.provider_router.provider_router.get_quote",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("live quote should not be used")),
    )

    report = services.report_service.generate(
        ReportGenerateRequest(
            report_type="paper_portfolio_review",
            source_type="paper_portfolio_snapshot",
            source_id=snapshot.snapshot_id,
        )
    )

    assert report.report_type == "paper_portfolio_review"
    assert report.source_type == "paper_portfolio_snapshot"
    assert report.execution_guard["auto_trade"] is False
    assert report.payload["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert "execution_guard.auto_trade=false" in report.content


def test_decision_journal_link_snapshot_explicit_omitted_idempotent_conflict_and_missing(monkeypatch, services, tmp_path):
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

    first = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    services.rebalance_draft_service.confirm(first.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    first_review = services.pre_trade_review_service.create(draft_id=first.draft_id, strict_status=True)
    services.paper_trading_service.create(first_review.review_id, source_mode="http")
    first_entry = services.repo.get_decision_journal_entry_by_decision_id(first.decision_id)
    assert first_entry is not None

    second = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(second.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    second_review = services.pre_trade_review_service.create(draft_id=second.draft_id, strict_status=True)
    services.paper_trading_service.create(second_review.review_id, source_mode="http")
    second_entry = services.repo.get_decision_journal_entry_by_decision_id(second.decision_id)
    assert second_entry is not None

    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    explicit = services.decision_journal_service.link_snapshot(first_entry.entry_id, snapshot.snapshot_id)
    assert explicit["snapshot_id"] == snapshot.snapshot_id

    same = services.decision_journal_service.link_snapshot(first_entry.entry_id, snapshot.snapshot_id)
    assert same["snapshot_id"] == snapshot.snapshot_id

    with pytest.raises(ValueError):
        services.decision_journal_service.link_snapshot(second_entry.entry_id, snapshot.snapshot_id)

    newer_snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    auto = services.decision_journal_service.link_snapshot(second_entry.entry_id)
    assert auto["snapshot_id"] == newer_snapshot.snapshot_id

    missing_services = create_services(
        db_path=tmp_path / "missing-journal.sqlite3",
        files_root=tmp_path / "missing-journal-files",
    )
    draft = missing_services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    missing_entry = missing_services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert missing_entry is not None
    with pytest.raises(ValueError):
        missing_services.decision_journal_service.link_snapshot(missing_entry.entry_id)


def test_paper_portfolio_review_report_auto_links_decision_journal_when_snapshot_is_linked(monkeypatch, services):
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

    draft = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    services.paper_trading_service.create(review.review_id, source_mode="http")
    entry = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry is not None

    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    services.decision_journal_service.link_snapshot(entry.entry_id, snapshot.snapshot_id)
    report = services.report_service.generate(
        ReportGenerateRequest(
            report_type="paper_portfolio_review",
            source_type="paper_portfolio_snapshot",
            source_id=snapshot.snapshot_id,
        )
    )
    linked = services.repo.get_decision_journal_entry(entry.entry_id)
    assert linked is not None
    assert linked.report_id == report.report_id

    unlinked_snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    other_report = services.report_service.generate(
        ReportGenerateRequest(
            report_type="paper_portfolio_review",
            source_type="paper_portfolio_snapshot",
            source_id=unlinked_snapshot.snapshot_id,
        )
    )
    assert other_report.report_id != report.report_id
    assert services.repo.get_decision_journal_entry_by_snapshot_id(unlinked_snapshot.snapshot_id) is None


def test_decision_journal_summary_reads_snapshot_payload_and_persisted_paper_order_only(monkeypatch, services):
    quote_map = {"AAPL": 400.0, "HK00700": 350.0}
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
        item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
        for item in holdings
    }
    prices.update(quote_map)
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
    monkeypatch.setattr(
        "backend.app_services.decision_journal_service.DecisionJournalService._current_price",
        lambda self, symbol, snapshot: quote_map.get(symbol.upper(), 0.0),
    )

    draft = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    order = services.paper_trading_service.create(review.review_id, source_mode="http")
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    entry = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry is not None
    services.decision_journal_service.link_snapshot(entry.entry_id, snapshot.snapshot_id)

    another = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(another.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))

    summary = services.decision_journal_service.summarize_outcomes()

    assert summary["total_suggestions"] == 2
    assert summary["paper_tracked_count"] == 1
    assert summary["closed_count"] == 0
    assert summary["average_paper_pnl"] == round((order.paper_price - quote_map["AAPL"]) * order.paper_quantity_estimate, 4)


def test_decision_journal_close_requires_paper_order_and_snapshot_then_is_idempotent(monkeypatch, services):
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

    draft = services.rebalance_draft_service.create({"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http")
    entry = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert entry is not None
    with pytest.raises(ValueError):
        services.decision_journal_service.close_entry(entry.entry_id)

    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)
    services.paper_trading_service.create(review.review_id, source_mode="http")
    tracked_entry = services.repo.get_decision_journal_entry_by_decision_id(draft.decision_id)
    assert tracked_entry is not None
    assert tracked_entry.status == "paper_tracked"
    with pytest.raises(ValueError):
        services.decision_journal_service.close_entry(tracked_entry.entry_id)

    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="test")
    services.decision_journal_service.link_snapshot(tracked_entry.entry_id, snapshot.snapshot_id)
    closed = services.decision_journal_service.close_entry(tracked_entry.entry_id, "done")
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None
    assert closed["close_note"] == "done"

    again = services.decision_journal_service.close_entry(tracked_entry.entry_id, "ignored")
    assert again["status"] == "closed"
    assert again["closed_at"] == closed["closed_at"]
    assert again["close_note"] == "done"

    summary = services.decision_journal_service.summarize_outcomes()
    assert summary["paper_tracked_count"] == 1
    assert summary["closed_count"] == 1


@pytest.mark.parametrize(
    ("mutator", "expected_guard"),
    [
        (
            lambda output: output["execution_guard"].__setitem__("auto_trade", True),
            {"auto_trade": True, **{k: v for k, v in CANONICAL_EXECUTION_GUARD.items() if k != "auto_trade"}},
        ),
        (
            lambda output: output["execution_guard"].__setitem__("unexpected_live_flag", True),
            {**CANONICAL_EXECUTION_GUARD, "unexpected_live_flag": True},
        ),
        (
            lambda output: output["execution_guard"].__setitem__("paper_trading", "live"),
            {"paper_trading": "live", **{k: v for k, v in CANONICAL_EXECUTION_GUARD.items() if k != "paper_trading"}},
        ),
        (
            lambda output: output.pop("execution_guard", None),
            None,
        ),
        (
            lambda output: output["execution_guard"].pop("real_order", None),
            {"auto_trade": False, "place_real_order_enabled": False, "paper_trading": "sandbox_only"},
        ),
    ],
)
def test_pre_trade_review_blocks_tampered_or_missing_execution_guard(services, mutator, expected_guard):
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))

    saved = services.repo.get_rebalance_draft(draft.draft_id)
    assert saved is not None
    mutator(saved.output)
    services.repo.save_rebalance_draft(saved)

    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)

    assert review.status == PreTradeReviewStatus.BLOCKED
    assert "execution_guard_unsafe" in review.blocker_codes
    assert review.execution_guard == (expected_guard or {})

    guard_check = next(item for item in review.checklist if item["code"] == "execution_guard_safe")
    assert guard_check["status"] == "blocked"
    assert guard_check["actual_value"]["draft_output_execution_guard"] == expected_guard

    with pytest.raises(ValueError):
        services.paper_trading_service.create(review.review_id, source_mode="http")


def test_paper_trading_blocks_tampered_saved_review_execution_guard(monkeypatch, services):
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
    draft = services.rebalance_draft_service.create({"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http")
    services.rebalance_draft_service.confirm(draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready"))
    review = services.pre_trade_review_service.create(draft_id=draft.draft_id, strict_status=True)

    saved_review = services.repo.get_pre_trade_review(review.review_id)
    assert saved_review is not None
    saved_review.execution_guard["unexpected_live_flag"] = True
    services.repo.save_pre_trade_review(saved_review)

    with pytest.raises(ValueError):
        services.paper_trading_service.create(review.review_id, source_mode="http")
    assert services.paper_trading_service.list(review_id=review.review_id) == []


def test_risk_policy_rules_reject_invalid_thresholds_and_negative_values():
    with pytest.raises(ValidationError):
        RiskPolicyRules(single_position_max_weight_pct=10, single_position_warning_weight_pct=11)

    with pytest.raises(ValidationError):
        RiskPolicyRules(draft_valid_hours=-1)

    with pytest.raises(ValidationError):
        RiskPolicyRules(monitor_default_cooldown_seconds=-5)


def test_activate_policy_keeps_single_active_and_default_in_repo(services):
    created = services.risk_policy_service.create_policy(
        RiskPolicy(
            policy_id="balanced-growth",
            name="Balanced Growth",
            description="lighter concentration guard",
            updated_at="2024-01-01T00:00:00+00:00",
            rules=RiskPolicyRules(
                single_position_max_weight_pct=20,
                single_position_warning_weight_pct=16,
                sector_max_weight_pct=45,
                draft_valid_hours=12,
                rebalance_min_delta_pct=1.5,
                monitor_default_cooldown_seconds=900,
            ),
        )
    )

    activated = services.risk_policy_service.activate_policy(created.policy_id or "balanced-growth")
    flags = {item.policy_id: (item.is_active, item.is_default) for item in services.repo.list_risk_policies()}

    assert activated.policy_id == "balanced-growth"
    assert activated.updated_at != "2024-01-01T00:00:00+00:00"
    assert sum(1 for active, default in flags.values() if active) == 1
    assert sum(1 for active, default in flags.values() if default) == 1
    assert flags["balanced-growth"] == (True, True)
    assert flags["default-conservative"] == (False, False)


def test_permission_allows_draft_but_blocks_execution(services):
    services.permission_guard.require(AuthorityLevel.A4, AuthorityLevel.A4, "draft_order")
    with pytest.raises(PermissionDenied) as exc:
        services.permission_guard.block_real_order()
    assert "real order execution is disabled" in str(exc.value)


def test_copilot_routes_and_streams_events(services):
    run = services.copilot_service.create_run(
        CopilotRequest(message="分析 AAPL 风险", page="stock", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert run.skill == "risk-officer"
    assert [event.type for event in events][-1] == "final"
    assert "disclaimer" in events[-1].payload
    assert events[-1].payload["skill_trace"]
    assert events[-1].payload["skill_trace"][-1]["skill"] == "report-writer"
    assert events[-1].payload["skill_trace"][-1]["status"] == "planned"


def test_copilot_rebalance_uses_multi_skill_trace(services):
    run = services.copilot_service.create_run(
        CopilotRequest(message="先分析 AAPL 风险，再给出调仓草案", page="holdings", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )
    task = services.repo.get_task(run.task_id)
    skills = [item["skill"] for item in task.skill_trace]
    assert skills == [
        "stock-researcher",
        "risk-officer",
        "rebalance-planner",
        "report-writer",
        "execution-agent-disabled",
    ]
    assert skills.index("risk-officer") < skills.index("rebalance-planner")
    assert all({"step", "skill", "status", "handoff"} <= set(item) for item in task.skill_trace)
    assert task.skill_trace[-1]["status"] == "blocked"
    assert "real order execution is disabled" in task.skill_trace[-1]["blocked_reason"]

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert any(event.type == "skill_trace" for event in events)
    assert events[-1].payload["skill_trace"][-1]["skill"] == "execution-agent-disabled"
    assert "auto_trade_false" in events[-1].payload["evidence_refs"]
    assert events[-1].payload["draft_id"].startswith("draft_")
    assert events[-1].payload["draft_status"] == "pending_user_confirmation"


def test_copilot_strategy_backtest_routes_to_strategy_analyst_and_records_ledger(services):
    services.strategy_service.create_strategy(
        StrategySpec(
            name="Sector Watch",
            strategy_type="sector_watch",
            risk_level="medium",
            universe=["AAPL", "HK00700"],
            parameters={"lookback_days": 9},
            tags=["sector"],
        )
    )
    run = services.copilot_service.create_run(
        CopilotRequest(message="回测 AAPL 策略", page="strategy", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )
    task = services.repo.get_task(run.task_id)

    assert run.intent == "strategy_backtest"
    assert run.skill == "strategy-analyst"
    assert [item["skill"] for item in task.skill_trace] == ["strategy-analyst", "report-writer"]

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "reasoning", "tool_call", "tool_result", "partial_answer", "final"]
    assert events[2].payload["tool"] == "run_strategy_backtest"
    assert events[3].payload["result"]["strategy_id"] == "concentration-control"
    assert events[-1].payload["execution_guard"]["research_only"] is True
    assert events[-1].payload["execution_guard"]["auto_trade"] is False
    assert "backtest_run" in events[-1].payload["tool_evidence_refs"]
    executions = services.repo.list_tool_executions(task_id=run.task_id)
    assert [(item.tool, item.domain, item.status) for item in executions] == [("run_strategy_backtest", "strategy", "succeeded")]


def test_fake_embedded_client_stream_is_forwarded_through_copilot_stream(services):
    class FakeEmbeddedAdapter(DeerFlowClientAdapter):
        async def stream(self, *, run_id, task_id, skill, message, context, skill_trace=None,
                         **kwargs):
            yield {"type": "partial_answer", "payload": {"text": "fake embedded partial"}}
            yield {"type": "tool_call", "payload": {"call_id": "call_1", "tool": "get_quote", "arguments": {"symbol": "AAPL"}}}
            yield {"type": "tool_result", "payload": {"call_id": "call_1", "tool": "get_quote", "result": {"last": 193.7}}}
            yield {
                "type": "final",
                "payload": {"conclusion": "fake embedded final", "usage": {"total_tokens": 5}},
            }

    services.copilot_service.deerflow = FakeEmbeddedAdapter()
    run = services.copilot_service.create_run(
        CopilotRequest(message="分析 AAPL 风险", page="stock", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "partial_answer", "tool_call", "tool_result", "final"]
    assert events[1].payload["text"] == "fake embedded partial"
    assert events[2].payload["tool"] == events[3].payload["tool"] == "get_quote"
    assert events[-1].payload["conclusion"] == "fake embedded final"
    assert events[-1].payload["usage"] == {"total_tokens": 5}
    assert events[-1].payload["skill_trace"][-1]["skill"] == "report-writer"


def test_prompt_envelope_contains_expected_sections_and_excludes_full_dumps(services):
    captured = {}

    class FakeClient:
        async def stream(self, **kwargs):
            captured.update(kwargs)
            yield ("end", {"usage_metadata": {"total_tokens": 1}})

    services.copilot_service.deerflow.mode = "embedded"
    services.copilot_service.deerflow.client = FakeClient()
    run = services.copilot_service.create_run(
        CopilotRequest(message="分析 AAPL 风险", page="stock", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    envelope = json.loads(captured["message"])

    assert [event.type for event in events] == ["skill_trace", "final"]
    assert set(envelope) == {
        "envelope_version",
        "user_message",
        "current_page",
        "skill_trace",
        "condensed_stock_context",
        "condensed_page_context",
        "safety_constraints",
    }
    assert envelope["envelope_version"] == "v0.20"
    assert envelope["current_page"] == "stock"
    assert envelope["user_message"] == "分析 AAPL 风险"
    assert envelope["condensed_stock_context"]["symbol"] == "AAPL"
    assert isinstance(envelope["condensed_page_context"], dict)
    assert "holdings" in envelope["condensed_page_context"]
    assert "position_count" in envelope["condensed_page_context"]["holdings"]
    assert "holding_summary" in envelope["condensed_stock_context"]
    assert "latest_report_ref" in envelope["condensed_stock_context"]
    assert "_authority_level" not in captured["message"]
    assert "secret" in " ".join(envelope["safety_constraints"]).lower()
    assert "environment" not in captured["message"].lower()
    assert "full_watchlist" not in captured["message"].lower()
    assert "tool_execution" not in captured["message"].lower()
    assert "content" not in json.dumps(envelope["condensed_stock_context"].get("latest_report_ref", {}), ensure_ascii=False)


def test_build_prompt_envelope_trims_runtime_context():
    envelope = build_prompt_envelope(
        user_message="分析 AAPL 风险",
        skill_trace=[{"step": 1, "skill": "stock-researcher", "purpose": "读取上下文", "authority_level": "A2", "status": "planned", "tools": ["get_stock_context"]}],
        context={
            "_authority_level": "A4",
            "symbol": "AAPL",
            "name": "Apple",
            "market": "NASDAQ",
            "industry": "Consumer Electronics",
            "sector": "Technology",
            "price": {"last": 193.7, "change_pct": 1.2, "updated_at": "now", "source": "mock_adapter", "degraded": False},
            "relation": {"in_watchlist": True, "in_holdings": True, "monitored": True},
            "holding": {"weight_pct": 18.5, "market_value": 1000000, "quantity": 9999},
            "ai_state": {"score": 82, "risk_label": "集中度高", "stance": "谨慎增持", "confidence": "medium"},
            "latest_report": {"report_id": "report_aapl", "generated_at": "now", "content": "should-not-leak"},
            "watchlist": [{"symbol": "AAPL"}],
            "history": [{"close": 1}],
            "env": {"OPENAI_API_KEY": "secret"},
        },
    )

    dumped = json.dumps(envelope, ensure_ascii=False)
    assert envelope["condensed_stock_context"]["holding_summary"] == {"weight_pct": 18.5, "market_value": 1000000, "pnl_pct": None}
    assert "quantity" not in dumped
    assert '"watchlist":' not in dumped
    assert "history" not in dumped
    assert "OPENAI_API_KEY" not in dumped
    assert "should-not-leak" not in dumped


def test_prompt_envelope_includes_page_scoped_context_without_full_payloads():
    envelope = build_prompt_envelope(
        user_message="今天我需要处理什么？",
        skill_trace=[{"step": 1, "skill": "risk-officer", "purpose": "读取待办", "authority_level": "A3", "status": "planned"}],
        context={
            "_authority_level": "A4",
            "page": "overview",
            "overview": {
                "inbox": {
                    "summary": {"open_count": 2, "high_count": 1},
                    "items": [{"item_key": "x", "title": "处理草案", "payload": "short"}],
                },
                "reports": {"items": [{"report_id": "report_1", "content": "should-not-leak"}]},
            },
            "symbol_summary": {"symbol": "AAPL", "name": "Apple", "holding": {"weight_pct": 18.5, "quantity": 999}},
        },
    )

    dumped = json.dumps(envelope, ensure_ascii=False)
    assert envelope["current_page"] == "overview"
    assert envelope["condensed_stock_context"]["symbol"] == "AAPL"
    assert envelope["condensed_page_context"]["overview"]["inbox"]["summary"]["open_count"] == 2
    assert "should-not-leak" not in dumped
    assert "_authority_level" not in dumped


def test_stub_copilot_stream_uses_tool_bridge_events(services):
    run = services.copilot_service.create_run(
        CopilotRequest(message="分析 AAPL 风险", page="stock", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "reasoning", "tool_call", "tool_result", "partial_answer", "final"]
    assert events[2].payload["tool"] == "evaluate_policy_risk"
    # authority_level rides on the tool_result payload (from the bridge spec), not the
    # tool_call event — the tool_call payload mirrors the real mapper ({call_id,tool,arguments}).
    assert events[3].payload["authority_level"] == "A3"
    assert events[3].payload["tool"] == "evaluate_policy_risk"
    assert any(item["symbol"] == "AAPL" for item in events[3].payload["result"]["risks"])
    assert "risk_policy" in events[-1].payload["tool_evidence_refs"]
    executions = services.repo.list_tool_executions(task_id=run.task_id)
    assert [(item.tool, item.status, item.call_id, item.source_mode) for item in executions] == [
        ("evaluate_policy_risk", "succeeded", "call_evaluate_policy_risk", "stub")
    ]
    assert executions[0].run_id == run.run_id
    assert executions[0].domain == "risk"
    assert executions[0].arguments == {}


def test_copilot_risk_preference_phrase_keeps_expected_event_chain(services):
    run = services.copilot_service.create_run(
        CopilotRequest(message="按我的风险偏好扫描持仓", page="holdings", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "reasoning", "tool_call", "tool_result", "partial_answer", "final"]
    assert events[2].payload["tool"] == "evaluate_policy_risk"
    assert events[3].payload["tool"] == "evaluate_policy_risk"


def test_stub_copilot_overview_chat_runs_research_tool(services):
    # Whether to call a tool is the model's judgment (no hard-coded chit-chat path);
    # the deterministic stub resolves the research tool, which contributes evidence.
    run = services.copilot_service.create_run(
        CopilotRequest(message="你好，给我一个工作台概览", page="overview", authority_level=AuthorityLevel.A2)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "reasoning", "tool_call", "tool_result", "partial_answer", "final"]
    assert events[2].payload["tool"] == "get_stock_context"
    assert events[-1].payload["tool_evidence_refs"]


def test_stub_copilot_monitor_explanation_uses_monitor_tool_chain(services):
    services.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})
    services.monitor_service.evaluate_once(source="manual", force=True)
    run = services.copilot_service.create_run(
        CopilotRequest(message="解释最近一条盯盘事件", page="monitor", authority_level=AuthorityLevel.A2)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "reasoning", "tool_call", "tool_result", "partial_answer", "final"]
    assert events[2].payload["tool"] == "get_monitor_events"
    assert events[3].payload["tool"] == "get_monitor_events"
    assert events[3].payload["result"]["items"]
    assert "disclaimer" in events[-1].payload


def test_fake_embedded_unknown_tool_is_passed_through_without_ledger(services):
    class FakeClient:
        async def stream(self, **kwargs):
            yield (
                "messages-tuple",
                [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [{"id": "call_1", "name": "deerflow_internal_tool", "args": {"symbol": "AAPL"}}],
                    }
                ],
            )
            yield (
                "messages-tuple",
                [{"type": "tool", "name": "deerflow_internal_tool", "tool_call_id": "call_1", "content": "ok"}],
            )
            yield ("end", {"usage_metadata": {"total_tokens": 5}})

    services.copilot_service.deerflow.client = FakeClient()
    run = services.copilot_service.create_run(
        CopilotRequest(message="分析 AAPL 风险", page="stock", symbol="AAPL", authority_level=AuthorityLevel.A4)
    )

    async def collect():
        return [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]

    events = asyncio.run(collect())
    assert [event.type for event in events] == ["skill_trace", "tool_call", "tool_result", "final"]
    assert events[1].payload["tool"] == "deerflow_internal_tool"
    assert services.repo.list_tool_executions(task_id=run.task_id) == []


def test_akshare_provider_is_unavailable_without_optional_dependency(monkeypatch):
    monkeypatch.setattr("backend.stock_domain.providers.find_spec", lambda name: None)
    provider = AkShareMarketDataProvider()

    assert provider.is_available() is False


@pytest.mark.parametrize("symbol", ["AAPL", "HK00700", "600519"])
def test_mock_market_data_provider_returns_quote_history_and_intel(symbol):
    provider = MockMarketDataProvider()

    quote = provider.get_quote(symbol)
    assert quote.source == provider.name
    assert quote.degraded is False
    assert quote.last > 0

    history = provider.get_history(symbol, days=5)
    assert history["symbol"] == symbol
    assert history["source"] == provider.name
    assert history["degraded"] is False
    assert history["degraded_reason"] is None
    assert len(history["items"]) == 5

    intel = provider.search_intel(symbol)
    assert intel["symbol"] == symbol
    assert intel["source"] == provider.name
    assert intel["degraded"] is False
    assert intel["degraded_reason"] is None
    assert intel["items"]


class UnavailablePrimaryProvider:
    name = "primary_stub"

    def is_available(self) -> bool:
        return False

    def get_quote(self, symbol: str) -> PriceSnapshot:  # pragma: no cover
        raise AssertionError("should not be called when provider is unavailable")

    def get_history(self, symbol: str, days: int = 30) -> dict:  # pragma: no cover
        raise AssertionError("should not be called when provider is unavailable")

    def search_intel(self, symbol: str, query: str = "") -> dict:  # pragma: no cover
        raise AssertionError("should not be called when provider is unavailable")

    def get_market_review(self) -> dict:  # pragma: no cover
        raise AssertionError("should not be called when provider is unavailable")

    def get_sectors(self) -> dict:  # pragma: no cover
        raise AssertionError("should not be called when provider is unavailable")


class RaisingPrimaryProvider:
    name = "primary_stub"

    def is_available(self) -> bool:
        return True

    def get_quote(self, symbol: str) -> PriceSnapshot:
        raise ProviderError(f"quote failed for {symbol}")

    def get_history(self, symbol: str, days: int = 30) -> dict:
        raise ProviderError(f"history failed for {symbol}")

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError(f"intel failed for {symbol}")

    def get_market_review(self) -> dict:
        raise ProviderError("review failed")

    def get_sectors(self) -> dict:
        raise ProviderError("sectors failed")


def test_provider_router_falls_back_to_mock_when_primary_is_unavailable():
    router = ProviderRouter(primary=UnavailablePrimaryProvider(), fallback=MockMarketDataProvider())

    quote = router.get_quote("600519")
    assert quote.source == "mock_adapter"
    assert quote.degraded is True
    assert quote.degraded_reason == "primary_stub optional dependency is not installed"
    status = router.status().to_dict()
    assert status["akshare_available"] is False
    assert status["active_provider"] == "mock_adapter"
    assert status["fallback_provider"] == "mock_adapter"
    assert status["degraded"] is True
    assert status["degraded_reason"] == "primary_stub optional dependency is not installed"
    assert status["capabilities"]["quote"]["degraded_reason"] == "primary_stub optional dependency is not installed"

    history = router.get_history("HK00700", days=3)
    assert history["source"] == "mock_adapter"
    assert history["degraded"] is True
    assert history["degraded_reason"] == "primary_stub optional dependency is not installed"
    assert len(history["items"]) == 3

    intel = router.search_intel("600519")
    assert intel["source"] == "mock_adapter"
    assert intel["degraded"] is True
    assert intel["degraded_reason"] == "primary_stub optional dependency is not installed"
    assert intel["items"]


def test_provider_router_falls_back_to_mock_when_primary_raises():
    router = ProviderRouter(primary=RaisingPrimaryProvider(), fallback=MockMarketDataProvider())

    quote = router.get_quote("600519")
    assert quote.source == "mock_adapter"
    assert quote.degraded is True
    assert quote.degraded_reason == "primary_stub: quote failed for 600519"
    status = router.status().to_dict()
    assert status["akshare_available"] is True
    assert status["active_provider"] == "mock_adapter"
    assert status["fallback_provider"] == "mock_adapter"
    assert status["degraded"] is True
    assert status["degraded_reason"] == "primary_stub: quote failed for 600519"
    assert status["capabilities"]["quote"]["degraded_reason"] == "primary_stub: quote failed for 600519"

    history = router.get_history("HK00700", days=4)
    assert history["source"] == "mock_adapter"
    assert history["degraded"] is True
    assert history["degraded_reason"] == "primary_stub: history failed for HK00700"
    assert len(history["items"]) == 4

    intel = router.search_intel("600519")
    assert intel["source"] == "mock_adapter"
    assert intel["degraded"] is True
    assert intel["degraded_reason"] == "primary_stub: intel failed for 600519"
    assert intel["items"]


class HealthyCnOnlyPrimaryProvider:
    name = "akshare"

    def is_available(self) -> bool:
        return True

    def get_quote(self, symbol: str) -> PriceSnapshot:
        return PriceSnapshot(last=1688.0, change_pct=1.2, updated_at="now", source=self.name)

    def get_history(self, symbol: str, days: int = 30) -> dict:
        return {
            "symbol": symbol,
            "source": self.name,
            "updated_at": "now",
            "degraded": False,
            "degraded_reason": None,
            "coverage": {"market": "CN"},
            "items": [{"day": 1, "date": "2026-05-01", "open": 1, "high": 2, "low": 1, "close": 2}],
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        return {
            "symbol": symbol,
            "query": query,
            "source": self.name,
            "updated_at": "now",
            "degraded": False,
            "degraded_reason": None,
            "coverage": {"market": "CN"},
            "items": [{"type": "profile", "title": "真实情报", "source": self.name, "confidence": "high"}],
        }

    def get_market_review(self) -> dict:
        return {
            "status": "上涨居多",
            "summary": "真实市场概览",
            "source": self.name,
            "updated_at": "now",
            "degraded": False,
            "degraded_reason": None,
            "coverage": {"market": "CN"},
            "indices": [{"code": "sh000001", "name": "上证指数", "last": 3200, "change_pct": 0.8, "turnover": 10}],
        }

    def get_sectors(self) -> dict:
        return {
            "source": self.name,
            "updated_at": "now",
            "degraded": False,
            "degraded_reason": None,
            "coverage": {"market": "CN", "dimension": "industry"},
            "items": [{"sector": "白酒", "signal": "强势拉升", "symbols": ["贵州茅台"]}],
        }


def test_provider_router_keeps_hk_us_request_degraded_without_polluting_global_status():
    router = ProviderRouter(primary=HealthyCnOnlyPrimaryProvider(), fallback=MockMarketDataProvider())

    us_history = router.get_history("AAPL", days=3)
    assert us_history["source"] == "akshare"
    assert us_history["degraded"] is False

    status = router.status().to_dict()
    assert status["active_provider"] == "akshare"
    assert status["degraded"] is False
    assert status["capabilities"]["history"]["active_provider"] == "akshare"


def test_provider_router_reports_capability_status_for_cn_primary():
    router = ProviderRouter(primary=HealthyCnOnlyPrimaryProvider(), fallback=MockMarketDataProvider())

    assert router.get_quote("600519").source == "akshare"
    assert router.get_market_review()["source"] == "akshare"
    assert router.get_sectors()["source"] == "akshare"

    status = router.status().to_dict()
    assert status["active_provider"] == "akshare"
    assert status["degraded"] is False
    for capability in ["quote", "history", "intel", "market", "sectors"]:
        assert status["capabilities"][capability]["active_provider"] == "akshare"
        assert status["capabilities"][capability]["degraded"] is False


def _make_hk_spot_df():
    import pandas as pd
    return pd.DataFrame([
        {"代码": "00700", "中文名称": "腾讯控股", "最新价": 456.4, "涨跌幅": 0.33},
        {"代码": "00001", "中文名称": "长和", "最新价": 42.5, "涨跌幅": -0.12},
    ])


def _make_hk_daily_df():
    import pandas as pd
    return pd.DataFrame([
        {"date": "2026-05-13", "open": 456.0, "high": 465.8, "low": 454.0, "close": 462.6, "volume": 26616535.0, "amount": 1.226e10},
        {"date": "2026-05-14", "open": 474.2, "high": 479.6, "low": 458.6, "close": 460.2, "volume": 39339032.0, "amount": 1.838e10},
        {"date": "2026-05-15", "open": 459.0, "high": 462.6, "low": 454.2, "close": 456.4, "volume": 26449868.0, "amount": 1.211e10},
    ])


def _make_us_daily_df():
    import pandas as pd
    return pd.DataFrame([
        {"date": "2026-05-13", "open": 293.5, "high": 300.92, "low": 293.5, "close": 298.87, "volume": 52684226.0},
        {"date": "2026-05-14", "open": 299.82, "high": 300.45, "low": 295.38, "close": 298.21, "volume": 35324918.0},
        {"date": "2026-05-15", "open": 297.9, "high": 303.2, "low": 296.52, "close": 300.23, "volume": 54862836.0},
    ])


def test_akshare_provider_get_quote_hk(monkeypatch):
    provider = AkShareMarketDataProvider()

    class MockAK:
        @staticmethod
        def stock_hk_spot():
            return _make_hk_spot_df()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)

    quote = provider.get_quote("HK00700")
    assert quote.last == 456.4
    assert quote.change_pct == 0.33
    assert quote.degraded is False
    assert quote.source == "akshare"
    assert quote.coverage == {"market": "HK", "mode": "real", "source_interface": "stock_hk_spot"}


def test_akshare_provider_get_quote_hk_not_found_raises(monkeypatch):
    provider = AkShareMarketDataProvider()

    class MockAK:
        @staticmethod
        def stock_hk_spot():
            return _make_hk_spot_df()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)
    monkeypatch.setattr(
        "backend.stock_domain.providers.get_stock",
        lambda symbol: {"symbol": symbol, "market": "HK", "name": "Unknown HK Stock"},
    )

    with pytest.raises(ProviderError, match="quote row not found"):
        provider.get_quote("HK00002")


def test_akshare_provider_get_quote_us_raises(monkeypatch):
    provider = AkShareMarketDataProvider()
    monkeypatch.setattr(provider, "is_available", lambda: True)

    with pytest.raises(ProviderError, match="phase1 real data only covers CN market"):
        provider.get_quote("AAPL")


def test_akshare_provider_get_history_hk(monkeypatch):
    provider = AkShareMarketDataProvider()

    class MockAK:
        @staticmethod
        def stock_hk_daily(symbol):
            assert symbol == "00700"
            return _make_hk_daily_df()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)

    history = provider.get_history("HK00700", days=3)
    assert history["source"] == "akshare"
    assert history["degraded"] is False
    assert history["degraded_reason"] is None
    assert history["coverage"] == {"market": "HK", "mode": "real", "source_interface": "stock_hk_daily"}
    assert len(history["items"]) == 3
    assert history["items"][0]["date"] == "2026-05-13"
    assert history["items"][0]["close"] == 462.6
    assert history["items"][0]["volume"] == 26616535.0
    assert history["items"][0]["amount"] == 1.226e10


def test_akshare_provider_get_history_us(monkeypatch):
    provider = AkShareMarketDataProvider()

    class MockAK:
        @staticmethod
        def stock_us_daily(symbol):
            assert symbol == "AAPL"
            return _make_us_daily_df()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)

    history = provider.get_history("AAPL", days=3)
    assert history["source"] == "akshare"
    assert history["degraded"] is False
    assert history["coverage"] == {"market": "US", "mode": "real", "source_interface": "stock_us_daily"}
    assert len(history["items"]) == 3
    assert history["items"][0]["amount"] == 0.0
    assert history["items"][0]["volume"] == 52684226.0


def test_akshare_provider_get_history_hk_empty_raises(monkeypatch):
    provider = AkShareMarketDataProvider()

    class MockAK:
        @staticmethod
        def stock_hk_daily(symbol):
            import pandas as pd
            return pd.DataFrame()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)

    with pytest.raises(ProviderError, match="empty history for HK00700"):
        provider.get_history("HK00700", days=3)


def test_akshare_provider_get_quote_hk_strips_hk_prefix_correctly(monkeypatch):
    provider = AkShareMarketDataProvider()

    captured_symbols = []

    class MockAK:
        @staticmethod
        def stock_hk_spot():
            return _make_hk_spot_df()

    monkeypatch.setattr(provider, "_ak", lambda: MockAK())
    monkeypatch.setattr(provider, "is_available", lambda: True)

    quote = provider.get_quote("HK00700")
    assert quote.last == 456.4
    assert quote.degraded is False

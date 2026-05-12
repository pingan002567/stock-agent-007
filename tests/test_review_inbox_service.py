from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.bootstrap import create_services
from backend.schemas import (
    PriceSnapshot,
    RebalanceDraftDecisionNoteRequest,
    ReportGenerateRequest,
    ReviewInboxStateStatus,
)


@pytest.fixture()
def services(tmp_path):
    return create_services(
        db_path=tmp_path / "review-inbox.sqlite3", files_root=tmp_path / "files"
    )


def _seed_confirmed_draft(services, symbol: str, target_weight_pct: float):
    draft = services.rebalance_draft_service.create(
        {"symbol": symbol, "target_weight_pct": target_weight_pct}, source_mode="http"
    )
    return services.rebalance_draft_service.confirm(
        draft.draft_id, RebalanceDraftDecisionNoteRequest(note="ready")
    )


def _seed_review(services, symbol: str, target_weight_pct: float):
    draft = _seed_confirmed_draft(services, symbol, target_weight_pct)
    return services.pre_trade_review_service.create(
        draft_id=draft.draft_id, strict_status=True
    )


def _seed_paper_tracked_entry(
    services, symbol: str = "HK00700", target_weight_pct: float = 8
):
    review = _seed_review(services, symbol, target_weight_pct)
    services.paper_trading_service.create(review.review_id, source_mode="http")
    return services.repo.get_decision_journal_entry_by_review_id(review.review_id)


def _degraded_quote(symbol: str) -> PriceSnapshot:
    return PriceSnapshot(
        last=101.2,
        change_pct=-1.3,
        updated_at="2026-05-13T10:00:00+00:00",
        source="mock_adapter",
        degraded=True,
        degraded_reason=f"degraded quote for {symbol}",
    )


def _healthy_quote(symbol: str) -> PriceSnapshot:
    return PriceSnapshot(
        last=101.2,
        change_pct=0.4,
        updated_at="2026-05-13T10:00:00+00:00",
        source="mock_adapter",
        degraded=False,
        degraded_reason=None,
    )


def test_review_inbox_generates_pending_and_expired_draft_items(services):
    pending = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    expired = services.rebalance_draft_service.create(
        {"symbol": "HK00700", "target_weight_pct": 8}, source_mode="http"
    )
    expired.valid_until = "2000-01-01T00:00:00+00:00"
    expired.updated_at = "2000-01-01T00:00:00+00:00"
    services.repo.save_rebalance_draft(expired)

    items = {item.item_key: item for item in services.review_inbox_service.list_items()}

    assert f"rebalance_draft:{pending.draft_id}:pending" in items
    expired_key = f"rebalance_draft:{expired.draft_id}:expired"
    assert expired_key in items
    assert items[expired_key].priority == "high"


def test_review_inbox_generates_passed_warning_and_blocked_review_items(
    monkeypatch, services
):
    monkeypatch.setattr(
        "backend.app_services.pre_trade_review_service.provider_router.get_quote",
        _healthy_quote,
    )
    passed = _seed_review(services, "HK00700", 8)
    warning = _seed_review(services, "HK00700", 13)
    blocked = _seed_review(services, "HK00700", 20)

    items = {
        item.review_id: item
        for item in services.review_inbox_service.list_items()
        if item.review_id
    }

    assert items[passed.review_id].severity == "passed"
    assert items[passed.review_id].priority == "medium"
    assert items[warning.review_id].severity == "warning"
    assert items[warning.review_id].priority == "medium"
    assert items[blocked.review_id].severity == "blocked"
    assert items[blocked.review_id].priority == "high"


def test_review_inbox_generates_decision_journal_missing_snapshot_and_not_closed_items(
    services,
):
    missing_snapshot = _seed_paper_tracked_entry(services, "HK00700", 8)
    linked = _seed_paper_tracked_entry(services, "AAPL", 15)
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="http")
    services.decision_journal_service.link_snapshot(
        linked.entry_id, snapshot.snapshot_id
    )

    items = {item.item_key: item for item in services.review_inbox_service.list_items()}

    assert f"decision_journal:{missing_snapshot.entry_id}:missing_snapshot" in items
    assert f"decision_journal:{linked.entry_id}:not_closed" in items


def test_review_inbox_generates_high_and_medium_monitor_event_items(services):
    items = {
        item.item_key: item
        for item in services.review_inbox_service.list_items()
        if item.source_type == "monitor_event"
    }

    assert "monitor_event:event_aapl_concentration" in items
    assert items["monitor_event:event_aapl_concentration"].priority == "high"
    assert "monitor_event:event_hk00700_sentiment" in items
    assert items["monitor_event:event_hk00700_sentiment"].priority == "medium"


def test_review_inbox_generates_warning_and_failed_report_quality_items(
    monkeypatch, services
):
    with monkeypatch.context() as patch:
        patch.setattr(
            "backend.stock_domain.quote_tools.provider_router.get_quote",
            _degraded_quote,
        )
        warning = services.report_service.generate(
            ReportGenerateRequest(
                report_type="stock_research", source_type="stock", source_id="AAPL"
            )
        )

    failed = services.report_service.generate(
        ReportGenerateRequest(
            report_type="stock_research", source_type="stock", source_id="HK00700"
        )
    )
    broken = services.repo.get_report(failed.report_id)
    broken.content = "missing heading"
    broken.disclaimer = ""
    broken.evidence_refs = []
    services.repo.save_report(broken)
    services.report_service.rerun_quality(failed.report_id)

    items = {
        item.report_id: item
        for item in services.review_inbox_service.list_items()
        if item.report_id
    }

    assert items[warning.report_id].severity == "warning"
    assert items[warning.report_id].priority == "high"
    assert items[failed.report_id].severity == "failed"
    assert items[failed.report_id].priority == "high"


def test_review_inbox_generates_degraded_snapshot_item(monkeypatch, services):
    monkeypatch.setattr(
        "backend.app_services.paper_portfolio_service.provider_router.get_quote",
        _degraded_quote,
    )
    snapshot = services.paper_portfolio_service.create_snapshot(source_mode="http")

    items = {
        item.snapshot_id: item
        for item in services.review_inbox_service.list_items()
        if item.snapshot_id
    }

    assert (
        items[snapshot.snapshot_id].item_key
        == f"paper_portfolio_snapshot:{snapshot.snapshot_id}:degraded"
    )
    assert items[snapshot.snapshot_id].priority == "high"


def test_review_inbox_overlay_defaults_to_open_without_state(services):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )

    item = services.review_inbox_service.get_current_item(
        f"rebalance_draft:{draft.draft_id}:pending"
    )

    assert item.status == ReviewInboxStateStatus.OPEN
    assert item.snoozed_until is None


def test_review_inbox_overlay_hides_dismissed_and_done_items(services):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    key = f"rebalance_draft:{draft.draft_id}:pending"

    services.review_inbox_service.dismiss(key, note="skip")
    assert all(
        item.item_key != key for item in services.review_inbox_service.list_items()
    )

    services.review_inbox_service.mark_done(key, note="done")
    assert all(
        item.item_key != key for item in services.review_inbox_service.list_items()
    )


def test_review_inbox_overlay_hides_future_snooze_and_shows_expired_snooze(services):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    key = f"rebalance_draft:{draft.draft_id}:pending"

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    services.review_inbox_service.snooze(key, snoozed_until=future, note="later")
    assert all(
        item.item_key != key for item in services.review_inbox_service.list_items()
    )
    assert services.review_inbox_service.summarize().snoozed_count == 1

    past = "2000-01-01T00:00:00+00:00"
    services.review_inbox_service.snooze(key, snoozed_until=past, note="expired")
    items = {item.item_key: item for item in services.review_inbox_service.list_items()}
    assert key in items
    assert items[key].status == ReviewInboxStateStatus.OPEN


def test_review_inbox_disappearing_source_ignores_saved_state(services):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    key = f"rebalance_draft:{draft.draft_id}:pending"
    services.review_inbox_service.dismiss(key, note="skip")

    services.rebalance_draft_service.confirm(
        draft.draft_id, RebalanceDraftDecisionNoteRequest(note="handled")
    )

    assert all(
        item.item_key != key for item in services.review_inbox_service.list_items()
    )


def test_review_inbox_pending_to_expired_key_transition_resets_to_visible_open(
    services,
):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    pending_key = f"rebalance_draft:{draft.draft_id}:pending"
    services.review_inbox_service.dismiss(pending_key, note="old state")

    stale = services.repo.get_rebalance_draft(draft.draft_id)
    stale.valid_until = "2000-01-01T00:00:00+00:00"
    stale.updated_at = "2000-01-01T00:00:00+00:00"
    services.repo.save_rebalance_draft(stale)

    items = {item.item_key: item for item in services.review_inbox_service.list_items()}
    expired_key = f"rebalance_draft:{draft.draft_id}:expired"
    assert pending_key not in items
    assert expired_key in items
    assert items[expired_key].status == ReviewInboxStateStatus.OPEN


def test_review_inbox_actions_only_write_review_inbox_state_and_leave_sources_unchanged(
    services,
):
    draft = services.rebalance_draft_service.create(
        {"symbol": "AAPL", "target_weight_pct": 15}, source_mode="http"
    )
    key = f"rebalance_draft:{draft.draft_id}:pending"
    before_draft = services.repo.get_rebalance_draft(draft.draft_id).model_dump(
        mode="json"
    )
    before_holdings = [
        item.model_dump(mode="json") for item in services.repo.list_holdings()
    ]

    services.review_inbox_service.dismiss(key, note="dismissed")
    services.review_inbox_service.snooze(
        key, snoozed_until="2099-01-01T00:00:00+00:00", note="later"
    )
    services.review_inbox_service.mark_done(key, note="done")

    after_draft = services.repo.get_rebalance_draft(draft.draft_id).model_dump(
        mode="json"
    )
    after_holdings = [
        item.model_dump(mode="json") for item in services.repo.list_holdings()
    ]
    state = services.repo.get_review_inbox_state(key)

    assert before_draft == after_draft
    assert before_holdings == after_holdings
    assert state is not None
    assert state.status == ReviewInboxStateStatus.DONE
    assert (
        services.repo.conn.execute(
            "SELECT COUNT(*) FROM review_inbox_state"
        ).fetchone()[0]
        == 1
    )

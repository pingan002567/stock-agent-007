from __future__ import annotations

import asyncio

import pytest

from backend.bootstrap import create_services


@pytest.fixture()
def services(tmp_path):
    return create_services(db_path=tmp_path / "monitor.sqlite3", files_root=tmp_path / "files")


def test_monitor_service_persists_status_rules_and_events(services):
    status = services.monitor_service.get_status()
    assert status.status == "paused"
    assert status.auto_start is False

    started = services.monitor_service.start()
    assert started.status == "running"
    assert services.repo.list_audit()[0].action == "monitor started"

    rule = services.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})
    assert rule.rule_type == "single_position_weight_gt"
    assert rule.threshold == 15
    assert rule.symbol == "AAPL"

    summary = services.monitor_service.evaluate_once(source="manual")
    assert summary["checked"] >= 1
    assert summary["matched"] >= 1
    assert summary["created"] >= 1
    assert summary["suppressed"] == 0
    assert summary["event_ids"]

    events = services.monitor_service.list_events(symbol="AAPL")
    assert events
    assert events[0].rule_id == rule.rule_id
    assert events[0].rule_type == "single_position_weight_gt"
    assert events[0].source == "manual"
    assert events[0].payload["symbol"] == "AAPL"

    explained = services.monitor_service.explain_event(events[0].event_id)
    assert explained["event"]["event_id"] == events[0].event_id
    assert explained["summary"]
    assert explained["evidence"]
    assert explained["suggested_actions"]

    overview = services.monitor_service.build_monitor_summary()
    assert overview["status"] == "running"
    assert overview["event_count"] >= 1
    assert overview["latest"]["event_id"] == events[0].event_id

    paused = services.monitor_service.pause()
    assert paused.status == "paused"


def test_monitor_service_cooldown_and_force_bypass(services):
    rule = services.monitor_service.upsert_rule(
        {
            "rule_type": "data_provider_degraded",
            "severity": "low",
            "cooldown_seconds": 3600,
        }
    )

    first = services.monitor_service.evaluate_once(source="manual")
    second = services.monitor_service.evaluate_once(source="manual")
    forced = services.monitor_service.evaluate_once(source="manual", force=True)

    assert first["matched"] == 1
    assert first["created"] == 1
    assert second["matched"] == 1
    assert second["created"] == 0
    assert second["suppressed"] == 1
    assert forced["created"] == 1

    events = services.repo.list_monitor_events(limit=10)
    dedupe_keys = [item.dedupe_key for item in events if item.rule_id == rule.rule_id]
    assert dedupe_keys
    assert len(dedupe_keys) == 2


def test_monitor_service_list_events_falls_back_and_loop_lifecycle(services):
    events = services.monitor_service.list_events()
    assert len(events) >= 3
    assert {item.severity for item in events} >= {"high", "medium"}
    explained = services.monitor_service.explain_event(event=events[0])
    assert explained["event"]["event_id"] == events[0].event_id

    async def run_loop_lifecycle():
        await services.monitor_service.start_loop()
        assert services.monitor_service.is_loop_running() is True
        await services.monitor_service.stop_loop()
        assert services.monitor_service.is_loop_running() is False

    asyncio.run(run_loop_lifecycle())


def test_monitor_service_does_not_fallback_when_persisted_events_filter_misses(services):
    services.monitor_service.upsert_rule({"symbol": "AAPL", "rule": "single_position_weight > 15%"})
    summary = services.monitor_service.evaluate_once(source="manual")
    assert summary["created"] == 1

    assert services.monitor_service.list_events(symbol="MSFT") == []
    assert services.monitor_service.list_events(severity="low") == []

    matches = services.monitor_service.list_events(symbol="AAPL", severity="high")
    assert len(matches) == 1
    assert matches[0].symbol == "AAPL"
    assert not matches[0].event_id.startswith("event_hk00700")


def test_monitor_service_uses_active_policy_defaults_but_preserves_explicit_values(services):
    created = services.monitor_service.upsert_rule({"symbol": "AAPL", "rule_type": "single_position_weight_gt"})
    assert created.threshold == 12
    assert created.cooldown_seconds == 3600

    explicit = services.monitor_service.upsert_rule(
        {
            "symbol": "AAPL",
            "rule_type": "single_position_weight_gt",
            "threshold": 19,
            "cooldown_seconds": 120,
        }
    )
    assert explicit.threshold == 19
    assert explicit.cooldown_seconds == 120

    policy = services.risk_policy_service.update_policy(
        "default-conservative",
        services.risk_policy_service.get_active_policy().model_copy(
            update={
                "rules": services.risk_policy_service.get_active_policy().rules.model_copy(
                    update={"single_position_warning_weight_pct": 14, "monitor_default_cooldown_seconds": 1800}
                )
            }
        ),
    )
    services.risk_policy_service.activate_policy(policy.policy_id)
    legacy = services.monitor_service.upsert_rule({"symbol": "AAPL"})
    assert legacy.threshold == 14
    assert legacy.cooldown_seconds == 1800

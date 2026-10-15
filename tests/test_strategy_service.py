from __future__ import annotations

from backend.bootstrap import create_services
from backend.schemas import StrategySpec


def make_services(tmp_path):
    return create_services(db_path=tmp_path / "strategy.sqlite3", files_root=tmp_path / "files")


def test_strategy_service_seeds_default_strategy_and_persists_backtests_after_delete(tmp_path):
    services = make_services(tmp_path)

    strategies = services.strategy_service.list_strategies()
    assert strategies
    assert strategies[0].strategy_id == "concentration-control"

    run = services.strategy_service.run_backtest("concentration-control")
    assert run.strategy_snapshot["strategy_id"] == "concentration-control"
    assert run.execution_guard["research_only"] is True
    assert all(item["auto_trade"] is False for item in run.candidate_actions)
    assert run.parameters["max_position_weight_pct"] == 15
    assert run.parameters["sector_limit_pct"] == 35
    assert run.parameters["rebalance_band_pct"] == 2.0
    assert run.risk_policy_ref and run.risk_policy_ref.policy_id == "default-conservative"

    assert services.strategy_service.delete_strategy("concentration-control") is True
    archived = services.strategy_service.get_backtest(run.run_id)
    assert archived.run_id == run.run_id
    assert services.strategy_service.list_backtests("concentration-control")[0].run_id == run.run_id


def test_strategy_service_crud_and_multi_strategy_backtests(tmp_path):
    services = make_services(tmp_path)

    created = services.strategy_service.create_strategy(
        StrategySpec(
            name="Price Momentum",
            strategy_type="price_momentum",
            risk_level="medium",
            universe=["AAPL", "HK00700"],
            parameters={"lookback_days": 12, "momentum_threshold_pct": 1.5},
            tags=["momentum"],
        )
    )
    assert created.strategy_id == "price-momentum"

    updated = services.strategy_service.update_strategy(
        created.strategy_id,
        StrategySpec(
            strategy_id=created.strategy_id,
            name="Price Momentum",
            strategy_type="price_momentum",
            risk_level="high",
            universe=["AAPL"],
            parameters={"lookback_days": 10, "momentum_threshold_pct": 2},
            tags=["momentum", "fast"],
        ),
    )
    assert updated.risk_level == "high"
    assert updated.version == created.version + 1

    run = services.strategy_service.run_backtest(updated.strategy_id)
    assert run.strategy_type == "price_momentum"
    assert run.metrics["sample_size"] == 1
    assert run.signals


def test_strategy_service_marks_degraded_runs_and_keeps_actions_read_only(tmp_path):
    services = make_services(tmp_path)
    services.strategy_service.create_strategy(
        StrategySpec(
            name="Sector Watch",
            strategy_type="sector_watch",
            risk_level="low",
            universe=["UNKNOWN1", "AAPL"],
            parameters={"lookback_days": 7},
            tags=["sector"],
        )
    )

    run = services.strategy_service.run_backtest("sector-watch")
    assert run.degraded is True
    assert run.degraded_reason
    assert all(item["auto_trade"] is False for item in run.candidate_actions)


def test_strategy_service_merges_policy_defaults_before_strategy_and_request_parameters(tmp_path):
    services = make_services(tmp_path)
    policy = services.risk_policy_service.update_policy(
        "default-conservative",
        services.risk_policy_service.get_active_policy().model_copy(
            update={
                "rules": services.risk_policy_service.get_active_policy().rules.model_copy(
                    update={
                        "single_position_max_weight_pct": 18,
                        "sector_max_weight_pct": 40,
                        "rebalance_min_delta_pct": 3.5,
                    }
                )
            }
        ),
    )
    services.risk_policy_service.activate_policy(policy.policy_id)
    services.strategy_service.create_strategy(
        StrategySpec(
            name="Policy Aware Concentration",
            strategy_type="concentration_control",
            risk_level="medium",
            universe=["AAPL"],
            parameters={"sector_limit_pct": 33},
            tags=["risk"],
        )
    )

    run = services.strategy_service.run_backtest(
        "policy-aware-concentration",
        parameters={"rebalance_band_pct": 1.5},
    )
    assert run.parameters["max_position_weight_pct"] == 18
    assert run.parameters["sector_limit_pct"] == 33
    assert run.parameters["rebalance_band_pct"] == 1.5

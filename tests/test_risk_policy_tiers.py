"""风险策略资金分层 / ETF 上限 / 单票亏损单测。"""

from __future__ import annotations

import pytest

from backend.bootstrap import create_services
from backend.schemas import HoldingPosition, RiskPolicyRules, StockMaster
from backend.stock_domain.catalog import infer_instrument_type, is_etf_like
from backend.stock_domain.risk_tools import analyze_portfolio_risk, resolve_effective_rules


@pytest.fixture()
def services(tmp_path):
    created = create_services(db_path=tmp_path / "workbench.sqlite3", files_root=tmp_path / "files")
    created.repo.seed_demo_portfolio()
    return created


def test_resolve_effective_rules_tier_boundaries():
    rules = RiskPolicyRules()
    assert resolve_effective_rules(rules, 9_999).single_position_max_weight_pct == 50
    assert resolve_effective_rules(rules, 9_999).min_holdings_count == 3
    assert resolve_effective_rules(rules, 9_999).capital_tier_label == "nav<10000"

    mid = resolve_effective_rules(rules, 10_000)
    assert mid.single_position_max_weight_pct == 25
    assert mid.min_holdings_count == 4
    assert mid.capital_tier_label == "nav<100000"

    assert resolve_effective_rules(rules, 99_999).single_position_max_weight_pct == 25

    base = resolve_effective_rules(rules, 100_000)
    assert base.single_position_max_weight_pct == 15
    assert base.sector_max_weight_pct == 35
    assert base.min_holdings_count == 7
    assert base.capital_tier_label == "base"
    assert base.etf_max_weight_pct == 100
    assert base.single_position_max_loss_pct_of_nav == 3


def test_old_policy_without_capital_tiers_still_parses():
    rules = RiskPolicyRules(
        single_position_max_weight_pct=15,
        single_position_warning_weight_pct=12,
        sector_max_weight_pct=35,
        draft_valid_hours=24,
        rebalance_min_delta_pct=2.0,
        monitor_default_cooldown_seconds=3600,
    )
    assert len(rules.capital_tiers) == 2
    assert rules.etf_max_weight_pct == 100


def test_small_nav_stock_vs_etf_weight(monkeypatch):
    monkeypatch.setattr(
        "backend.stock_domain.risk_tools.get_stock",
        lambda symbol: {
            "symbol": symbol,
            "sector": "宽基指数 / ETF" if symbol.startswith("51") else "消费 / 白酒",
            "instrument_type": "etf" if symbol.startswith("51") else "stock",
            "name": symbol,
            "industry": "ETF" if symbol.startswith("51") else "白酒",
            "aliases": [],
        },
    )
    stock_ok = analyze_portfolio_risk(
        [
            HoldingPosition(
                symbol="600519", name="茅台", quantity=1, market_value=3200, weight_pct=40
            ),
            HoldingPosition(
                symbol="000858", name="五粮液", quantity=1, market_value=2400, weight_pct=30
            ),
            HoldingPosition(
                symbol="AAPL", name="Apple", quantity=1, market_value=2400, weight_pct=30
            ),
        ],
        portfolio_nav=8_000,
    )
    assert not any(r["kind"] == "single_position_max" for r in stock_ok["risks"])

    stock_bad = analyze_portfolio_risk(
        [
            HoldingPosition(
                symbol="600519", name="茅台", quantity=1, market_value=4800, weight_pct=60
            ),
        ],
        portfolio_nav=8_000,
    )
    assert any(r["kind"] == "single_position_max" for r in stock_bad["risks"])

    etf_ok = analyze_portfolio_risk(
        [
            HoldingPosition(
                symbol="510300", name="沪深300ETF", quantity=100, market_value=7200, weight_pct=90
            ),
        ],
        portfolio_nav=8_000,
    )
    assert not any(r["kind"] == "etf_position_max" for r in etf_ok["risks"])
    assert etf_ok["effective_rules"]["etf_max_weight_pct"] == 100


def test_min_holdings_and_loss_of_nav(monkeypatch):
    monkeypatch.setattr(
        "backend.stock_domain.risk_tools.get_stock",
        lambda symbol: {
            "symbol": symbol,
            "sector": "大型科技",
            "instrument_type": "stock",
            "name": symbol,
            "industry": "",
            "aliases": [],
        },
    )
    result = analyze_portfolio_risk(
        [
            HoldingPosition(
                symbol="AAPL",
                name="Apple",
                quantity=10,
                market_value=50_000,
                weight_pct=50,
                cost=6000,
            ),
            HoldingPosition(
                symbol="MSFT",
                name="MSFT",
                quantity=10,
                market_value=50_000,
                weight_pct=50,
                cost=5000,
            ),
        ],
        portfolio_nav=100_000,
    )
    assert any(r["kind"] == "min_holdings" for r in result["risks"])
    assert any(r["kind"] == "single_position_loss_of_nav" for r in result["risks"])


def test_infer_etf_symbols():
    assert infer_instrument_type("510300", name="沪深300ETF") == "etf"
    assert infer_instrument_type("600519", name="贵州茅台") == "stock"
    assert is_etf_like(
        "512880",
        {"instrument_type": "etf", "symbol": "512880", "name": "证券ETF", "aliases": []},
    )


def test_seed_default_policy_has_tiers(services):
    policy = services.risk_policy_service.get_active_policy()
    assert policy.policy_id == "default-conservative"
    assert len(policy.rules.capital_tiers) >= 2
    assert policy.rules.etf_max_weight_pct == 100
    assert policy.rules.single_position_max_loss_pct_of_nav == 3
    master = services.repo.get_stock_master("510300")
    assert master is not None
    assert master.instrument_type == "etf"


def test_akshare_prefers_etf_hist_for_cn_etf(monkeypatch):
    from backend.stock_domain.providers import AkShareMarketDataProvider, ProviderError

    provider = AkShareMarketDataProvider()
    calls: list[str] = []

    class FakeAk:
        def fund_etf_hist_em(self, **kwargs):
            calls.append("etf")
            return [
                {"日期": "2026-01-02", "开盘": 1, "最高": 1.1, "最低": 0.9, "收盘": 1.05, "成交量": 100},
                {"日期": "2026-01-03", "开盘": 1.05, "最高": 1.2, "最低": 1.0, "收盘": 1.1, "成交量": 120},
            ]

        def stock_zh_a_hist(self, **kwargs):
            calls.append("stock")
            raise ProviderError("should not be primary for ETF")

    monkeypatch.setattr(provider, "_ak", lambda: FakeAk())
    monkeypatch.setattr(
        "backend.stock_domain.providers.get_stock",
        lambda symbol: {
            "symbol": symbol,
            "market": "CN",
            "name": "沪深300ETF",
            "instrument_type": "etf",
            "industry": "ETF",
            "sector": "宽基指数 / ETF",
            "aliases": [],
        },
    )
    result = provider.get_history("510300", days=2)
    assert result["items"]
    assert result["coverage"]["source_interface"] == "fund_etf_hist_em"
    assert "etf" in calls


def test_pre_trade_allows_etf_above_stock_cap(services):
    from backend.schemas import RebalanceDraftDecisionNoteRequest

    for h in list(services.repo.list_holdings()):
        services.repo.delete_holding(h.symbol)
    services.repo.upsert_stock_master(
        StockMaster(
            symbol="510300",
            name="沪深300ETF",
            market="CN",
            industry="ETF",
            sector="宽基指数 / ETF",
            instrument_type="etf",
        )
    )
    draft = services.rebalance_draft_service.create(
        {"symbol": "510300", "target_weight_pct": 80},
        source_mode="http",
    )
    services.rebalance_draft_service.confirm(
        draft.draft_id,
        RebalanceDraftDecisionNoteRequest(note="etf-ok"),
    )
    review = services.pre_trade_review_service.create(draft_id=draft.draft_id)
    assert "single_position_max_weight_exceeded" not in review.blocker_codes
    assert "etf_max_weight_exceeded" not in review.blocker_codes

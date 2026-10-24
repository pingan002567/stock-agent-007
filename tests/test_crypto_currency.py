"""加密货币接入持仓/自选：归一化、币种推断、分币种汇总、FX 降级。

这些断言对应 doc/CRYPTO_HOLDINGS_PLAN.md 的 DoD：
- BTC 不再被当成美股（normalize_symbol / inferMarket 两侧都要对）
- 分币种小计零依赖；折合总额与跨币种权重才依赖汇率
- 汇率缺失时给 None，**不按 1:1 硬算、不显示 0**
"""

from __future__ import annotations

import pytest

from backend.schemas import HoldingPosition
from backend.stock_domain import fx
from backend.stock_domain.catalog import get_stock, normalize_symbol
from backend.stock_domain.portfolio_tools import (
    holding_currency,
    summarize_portfolio,
    to_cny_amount,
)

RATES = {"CNY": 1.0, "USD": 6.68, "HKD": 0.86, "USDT": 6.68}


def _holding(symbol: str, value: float, currency: str = "") -> HoldingPosition:
    return HoldingPosition(
        symbol=symbol, name=symbol, quantity=1, market_value=value, weight_pct=0, currency=currency
    )


# ── 1. 符号归一化 ──────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BTC", "BTC"),
        ("btc", "BTC"),
        ("BTCUSDT", "BTC"),
        ("btc/usdt", "BTC"),
        ("ETH-USDT", "ETH"),
        ("eth_usdt", "ETH"),
        ("600519", "600519"),
        ("HK00700", "HK00700"),
        ("AAPL", "AAPL"),
    ],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


def test_crypto_market_is_not_us() -> None:
    stock = get_stock("BTC")
    assert stock is not None
    assert stock["market"] == "CRYPTO"
    assert stock["instrument_type"] == "crypto"


# ── 2. 币种推断 ────────────────────────────────────────────
def test_holding_currency_explicit_wins() -> None:
    assert holding_currency(_holding("BTC", 100, "USDT")) == "USDT"


@pytest.mark.parametrize(
    "symbol,expected",
    [("600519", "CNY"), ("HK00700", "HKD"), ("AAPL", "USD"), ("BTC", "USDT")],
)
def test_holding_currency_inferred_from_market(symbol: str, expected: str) -> None:
    assert holding_currency(_holding(symbol, 100)) == expected


def test_to_cny_amount_never_falls_back_to_one_to_one() -> None:
    assert to_cny_amount(100, "USD", RATES) == 668.0
    assert to_cny_amount(100, "USD", None) is None
    assert to_cny_amount(100, "XXX", RATES) is None


# ── 3. 分币种汇总 ──────────────────────────────────────────
def test_summary_converted_counts_weights() -> None:
    items = [
        _holding("600519", 33600, "CNY"),
        _holding("AAPL", 5715, "USD"),
        _holding("BTC", 6471.66, "USDT"),
    ]
    out = summarize_portfolio(items, available_cash=47000, rates=RATES)
    assert out["converted"] is True
    buckets = {b["currency"]: b for b in out["by_currency"]}
    assert buckets["CNY"]["native"] == 33600
    assert buckets["USD"]["cny"] == round(5715 * 6.68, 2)
    assert buckets["USDT"]["native"] == 6471.66
    # 总额 = 三个币种折算 + 现金
    expect_total = round(33600 + 5715 * 6.68 + 6471.66 * 6.68 + 47000, 2)
    assert out["total_value"] == expect_total
    # 权重分母 = 持仓市值（**不含现金**），与 risk_policy 的 portfolio_nav 一致
    assert out["weights"] is not None
    assert abs(sum(out["weights"].values()) - 100) < 0.05
    assert out["max_weight_pct"] == max(out["weights"].values())
    assert abs(out["weights"]["BTC"] - (6471.66 * 6.68) / out["market_value"] * 100) < 0.02


def test_summary_degraded_keeps_native_subtotals_only() -> None:
    items = [_holding("600519", 33600, "CNY"), _holding("BTC", 6471.66, "USDT")]
    out = summarize_portfolio(items, available_cash=47000, rates=None)
    assert out["converted"] is False
    # 折合三件套必须是 None —— 不许按 1:1 硬算
    assert out["market_value"] is None
    assert out["total_value"] is None
    assert out["cash_pct"] is None
    assert out["weights"] is None
    # 分币种小计照常
    buckets = {b["currency"]: b for b in out["by_currency"]}
    assert buckets["CNY"]["native"] == 33600
    assert buckets["USDT"]["native"] == 6471.66
    assert buckets["USDT"]["cny"] is None


# ── 4. FX 服务降级 ─────────────────────────────────────────
def test_fx_degraded_disables_conversion(monkeypatch) -> None:
    monkeypatch.setattr(fx, "_fetch_rates", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    fx.invalidate_cache()
    payload = fx.get_rates(refresh=True)
    assert payload["degraded"] is True
    assert payload["usd_cny"] is None
    assert fx.rates_for_conversion(payload) is None
    assert to_cny_amount(100, "USD", fx.rates_for_conversion(payload)) is None
    fx.invalidate_cache()


def test_fx_live_payload_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24",
            "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com",
            "usd_cny": 6.684864,
            "hkd_cny": 0.852381,
            "usdt_usd": 1.0,
            "degraded": False,
            "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    payload = fx.get_rates(refresh=True)
    rates = fx.rates_for_conversion(payload)
    assert rates == {"CNY": 1.0, "USD": 6.684864, "HKD": 0.852381, "USDT": 6.684864}
    assert payload["as_of"] == "2026-10-24"
    fx.invalidate_cache()


# ── 5. API ────────────────────────────────────────────────
def test_holdings_api_exposes_currency_and_buckets(tmp_path, monkeypatch) -> None:
    from tests.test_api import make_client

    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24",
            "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com",
            "usd_cny": 6.68,
            "hkd_cny": 0.86,
            "usdt_usd": 1.0,
            "degraded": False,
            "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    client.post(
        "/api/holdings/import-confirm",
        json=[
            {"symbol": "600519", "name": "贵州茅台", "quantity": 20, "market_value": 33600, "weight_pct": 0, "cost": 1605},
            {"symbol": "BTC", "name": "Bitcoin", "quantity": 0.08, "market_value": 6471.66, "weight_pct": 0, "cost": 76200},
        ],
    )
    body = client.get("/api/holdings").json()
    by_symbol = {item["symbol"]: item for item in body["items"]}
    assert by_symbol["BTC"]["market"] == "CRYPTO"
    assert by_symbol["BTC"]["currency"] == "USDT"
    assert by_symbol["BTC"]["market_value_native"] is not None
    assert {b["currency"] for b in body["summary"]["by_currency"]} >= {"CNY", "USDT"}
    assert body["fx"]["as_of"] == "2026-10-24"
    assert body["summary"]["converted"] is True
    fx.invalidate_cache()


def test_fx_rates_endpoint(tmp_path, monkeypatch) -> None:
    from tests.test_api import make_client

    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24",
            "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com",
            "usd_cny": 6.68,
            "hkd_cny": 0.86,
            "usdt_usd": 1.0,
            "degraded": False,
            "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    client = make_client(tmp_path)
    body = client.get("/api/fx/rates").json()
    assert body["to_cny"]["USD"] == 6.68
    assert body["as_of"] == "2026-10-24"
    assert body["degraded"] is False
    fx.invalidate_cache()


# ── 6. 行情：加密货币走 Gate，失败快速降级（不能落到 A 股 provider 死等）──
def test_crypto_quote_uses_gate_and_degrades_fast(monkeypatch) -> None:
    from backend.stock_domain import crypto_providers
    from backend.stock_domain.provider_router import provider_router

    monkeypatch.setattr(
        crypto_providers,
        "fetch_quote",
        lambda symbol: {
            "symbol": symbol,
            "last": 80895.7,
            "change_pct": -0.93,
            "high_24h": 82054.2,
            "low_24h": 80515.7,
            "quote_volume": 6.06e8,
            "source": "gate_spot",
        },
    )
    crypto_providers.invalidate_cache()
    quote = provider_router.get_quote("BTC", force=True)
    assert quote.degraded is False
    assert quote.last == 80895.7
    assert quote.source == "gate_spot"


def test_crypto_quote_failure_is_degraded_not_retried(monkeypatch) -> None:
    from backend.stock_domain import crypto_providers
    from backend.stock_domain.provider_router import provider_router

    calls: list[str] = []

    def boom(symbol: str):
        calls.append(symbol)
        raise RuntimeError("gate down")

    monkeypatch.setattr(crypto_providers, "fetch_quote", boom)
    crypto_providers.invalidate_cache()
    quote = provider_router.get_quote("ETH", force=True)
    assert quote.degraded is True
    assert quote.last == 0.0
    assert "加密货币行情不可用" in (quote.degraded_reason or "")
    # 只打一次源，不做跨源重试（备选源境内都不可达，重试只会拖垮持仓页）
    assert calls == ["ETH"]


def test_crypto_history_uses_gate_klines(monkeypatch) -> None:
    from backend.stock_domain import crypto_providers
    from backend.stock_domain.provider_router import provider_router

    monkeypatch.setattr(
        crypto_providers,
        "fetch_klines",
        lambda symbol, interval="1d", limit=60: [
            {"date": "2026-10-23", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            {"date": "2026-10-24", "open": 1.5, "high": 2.5, "low": 1, "close": 2.0, "volume": 12},
        ],
    )
    crypto_providers.invalidate_cache()
    hist = provider_router.get_history("BTC", days=2, force=True)
    assert hist["degraded"] is False
    assert hist["market"] == "CRYPTO"
    assert [bar["date"] for bar in hist["items"]] == ["2026-10-23", "2026-10-24"]


# ── 7. 衍生品（资金费率/持仓量/多空比/清算）────────────────
def _fake_gate(path: str, params=None):
    if path.endswith("/contracts/BTC_USDT"):
        return {
            "funding_rate_indicative": "0.000056",
            "funding_interval": 28800,
            "maintenance_rate": "0.003",
            "index_price": "80900.5",
        }
    if path.endswith("/tickers"):
        return [{"funding_rate": "0.0001", "mark_price": "80895.7", "last": "80895.7"}]
    if path.endswith("/funding_rate"):
        # 90 次历史，一半低于 0.0001 → 分位约 50%
        return [{"r": "0.00005" if i % 2 else "0.0002", "t": 1792800000 - i * 28800} for i in range(90)]
    if path.endswith("/contract_stats"):
        return [
            {
                "open_interest": 553686232,
                "lsr_account": 1.94,
                "lsr_taker": 0.97,
                "top_lsr_size": 0.77,
                "long_liq_usd": 5960211.8,
                "short_liq_usd": 450414.4,
            }
        ]
    raise AssertionError(f"unexpected path {path}")


def test_fetch_derivatives_computes_derived_fields(monkeypatch) -> None:
    from backend.stock_domain import crypto_providers

    monkeypatch.setattr(crypto_providers, "_get", _fake_gate)
    crypto_providers.invalidate_derivatives_cache()
    d = crypto_providers.fetch_derivatives("BTC")
    assert d["contract"] == "BTC_USDT"
    assert d["funding_rate"] == 0.0001
    assert d["funding_interval_hours"] == 8.0
    # 年化 = 单次费率 × 每年 1095 次结算
    assert d["funding_annualized_pct"] == round(0.0001 * 1095 * 100, 2)
    assert d["funding_percentile_90d"] is not None
    assert d["funding_samples"] == 90
    assert d["open_interest_usd"] == 553686232
    assert d["long_short_account_ratio"] == 1.94
    assert d["top_trader_long_short_ratio"] == 0.77
    assert d["liquidations_24h"]["long_usd"] == 5960211.8
    assert d["degraded"] is False
    crypto_providers.invalidate_derivatives_cache()


def test_derivatives_tool_degrades_on_unknown_coin() -> None:
    from backend.agent_runtime.tool_bridge import WorkbenchToolBridge

    handler = WorkbenchToolBridge._get_crypto_derivatives
    out = handler(None, {"symbol": "NOTACOIN"})
    assert out["degraded"] is True
    assert "不在加密货币标的表内" in out["degraded_reason"]
    assert handler(None, {})["degraded"] is True


def test_derivatives_tool_normalizes_pair() -> None:
    from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
    from backend.stock_domain import crypto_providers

    seen: list[str] = []

    def fake(symbol: str):
        seen.append(symbol)
        return {"symbol": symbol, "degraded": False}

    crypto_providers.fetch_derivatives = fake  # type: ignore[assignment]
    handler = WorkbenchToolBridge._get_crypto_derivatives
    out = handler(None, {"symbol": "btc/usdt"})
    assert seen == ["BTC"]
    assert out["degraded"] is False


# ── 8. 新增持仓接口 ────────────────────────────────────────
def test_add_holding_endpoint_stores_native_currency(tmp_path, monkeypatch) -> None:
    from tests.test_api import make_client

    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24", "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com", "usd_cny": 6.68, "hkd_cny": 0.86,
            "usdt_usd": 1.0, "degraded": False, "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")

    from backend.stock_domain.crypto_providers import invalidate_cache
    from backend.stock_domain.provider_router import provider_router

    invalidate_cache()
    provider_router._mem_cache.invalidate_prefix("CRYPTO:") if hasattr(
        provider_router._mem_cache, "invalidate_prefix"
    ) else None

    res = client.post("/api/holdings", json={"symbol": "btc/usdt", "quantity": 0.08, "cost": 76200})
    assert res.status_code == 200
    body = res.json()
    btc = next(i for i in body["items"] if i["symbol"] == "BTC")
    assert btc["market"] == "CRYPTO"
    assert btc["currency"] == "USDT"
    # market_value 是折算后的人民币，market_value_native 是原币
    assert btc["market_value_native"] is not None
    if btc["market_value"] is not None:
        assert btc["market_value"] == round(btc["market_value_native"] * 6.68, 2)
    # 未知标的要 400，不能静默建一条
    assert client.post("/api/holdings", json={"symbol": "ZZZZZZ", "quantity": 1}).status_code == 400
    fx.invalidate_cache()


def test_add_holding_rejects_zero_quantity(tmp_path) -> None:
    from tests.test_api import make_client

    client = make_client(tmp_path)
    res = client.post("/api/holdings", json={"symbol": "BTC", "quantity": 0})
    assert res.status_code == 422


# ── 9. 风控：权重按折算值实时算（P0 修复）────────────────
def _risk_client(tmp_path, monkeypatch, holdings):
    from tests.test_api import make_client

    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24", "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com", "usd_cny": 6.68, "hkd_cny": 0.86,
            "usdt_usd": 1.0, "degraded": False, "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    client.post("/api/holdings/import-confirm", json=holdings)
    return client


def test_risk_flags_concentration_with_real_weights(tmp_path, monkeypatch) -> None:
    """单票超限必须真的报警 —— 以前 weight_pct 恒 0，这条永远不触发。"""
    client = _risk_client(
        tmp_path,
        monkeypatch,
        [
            {"symbol": "600519", "name": "贵州茅台", "quantity": 100, "market_value": 900000, "weight_pct": 0, "cost": 1600},
            {"symbol": "000963", "name": "华东医药", "quantity": 100, "market_value": 20000, "weight_pct": 0, "cost": 26},
        ],
    )
    risk = client.get("/api/holdings/risk").json()
    kinds = {(r["kind"], r.get("symbol")) for r in risk["risks"]}
    assert ("single_position_max", "600519") in kinds
    hit = next(r for r in risk["risks"] if r["kind"] == "single_position_max")
    assert hit["severity"] == "high"
    # NAV = 900000 + 20000（都是人民币）
    assert risk["portfolio_nav"] == 920000
    assert hit["actual_value"] == round(900000 / 920000 * 100, 2)
    fx.invalidate_cache()


def test_risk_nav_converts_foreign_currency(tmp_path, monkeypatch) -> None:
    """NAV 必须折算：BTC 的 USDT 市值不能直接加进人民币 NAV。"""
    client = _risk_client(
        tmp_path,
        monkeypatch,
        [
            {"symbol": "600519", "name": "贵州茅台", "quantity": 100, "market_value": 100000, "weight_pct": 0, "cost": 1600},
            {"symbol": "BTC", "name": "Bitcoin", "quantity": 1, "market_value": 10000, "weight_pct": 0, "cost": 9000},
        ],
    )
    risk = client.get("/api/holdings/risk").json()
    # 100000 + 10000×6.68 = 166800（不是 110000）
    assert risk["portfolio_nav"] == round(100000 + 10000 * 6.68, 2)
    assert risk["nav_converted"] is True
    # BTC 折算后占 40.05%
    assert risk["crypto_weight_pct"] == round(10000 * 6.68 / (100000 + 10000 * 6.68) * 100, 2)
    fx.invalidate_cache()


def test_risk_flags_crypto_total_exposure(tmp_path, monkeypatch) -> None:
    """加密资产合计超过 crypto_max_weight_pct（默认 30%）要报，即使单币不超限。"""
    client = _risk_client(
        tmp_path,
        monkeypatch,
        [
            {"symbol": "600519", "name": "贵州茅台", "quantity": 100, "market_value": 600000, "weight_pct": 0, "cost": 1600},
            {"symbol": "BTC", "name": "Bitcoin", "quantity": 1, "market_value": 20000, "weight_pct": 0, "cost": 20000},
            {"symbol": "ETH", "name": "Ethereum", "quantity": 1, "market_value": 20000, "weight_pct": 0, "cost": 20000},
        ],
    )
    risk = client.get("/api/holdings/risk").json()
    kinds = [r["kind"] for r in risk["risks"]]
    assert "crypto_exposure_max" in kinds
    crypto_risk = next(r for r in risk["risks"] if r["kind"] == "crypto_exposure_max")
    assert crypto_risk["threshold_value"] == 30
    assert crypto_risk["severity"] == "high"
    fx.invalidate_cache()


# ── 10. 币圈定时任务与盯盘（P2）──────────────────────────
def test_crypto_duty_tasks_use_crypto_preamble_and_skip_cn_calendar() -> None:
    from backend.app_services import scheduler_service as sched

    crypto_tasks = [t for t in sched.DEFAULT_TASKS if sched.is_crypto_task(t)]
    assert {t["task_id"] for t in crypto_tasks} == {
        "sched_crypto_daily",
        "sched_crypto_asia",
        "sched_crypto_late",
    }
    for task in crypto_tasks:
        # 用加密货币专属 preamble：禁 A 股概念、要求衍生品与全市场情绪
        assert sched.preamble_for(task) is sched.CRYPTO_DUTY_PREAMBLE
        # 24/7：不走 CN 交易日历
        assert sched.uses_cn_session_calendar(task) is False
        assert sched.skip_reason_for(task) is None
        assert task.get("market") == "CRYPTO"
    # A 股任务不受影响
    cn = next(t for t in sched.DEFAULT_TASKS if t["task_id"] == "sched_premarket")
    assert sched.preamble_for(cn) is sched.DUTY_PREAMBLE
    assert sched.uses_cn_session_calendar(cn) is True


def test_crypto_preamble_bans_a_share_concepts() -> None:
    from backend.app_services.scheduler_service import CRYPTO_DUTY_PREAMBLE

    assert "禁止使用 A 股概念" in CRYPTO_DUTY_PREAMBLE
    assert "get_crypto_derivatives" in CRYPTO_DUTY_PREAMBLE
    assert "固定四段" in CRYPTO_DUTY_PREAMBLE
    # 四段契约里的收口工具必须still在
    assert "submit_duty_briefing" in CRYPTO_DUTY_PREAMBLE


class _RuleStub:
    """只为调用 matcher 提供一个 self（matcher 只用到 _rule_symbols）。"""

    def _rule_symbols(self, rule):
        return [rule.symbol] if rule.symbol else []


def test_monitor_funding_rate_rule(monkeypatch) -> None:
    from backend.app_services.monitor_service import MonitorService
    from backend.stock_domain import crypto_providers
    from backend.schemas import MonitorRule

    monkeypatch.setattr(
        crypto_providers,
        "fetch_derivatives",
        lambda symbol: {
            "symbol": symbol,
            "funding_rate": 0.0005,          # 0.05% 单次，超过 0.02% 阈值
            "funding_annualized_pct": 54.75,
            "funding_percentile_90d": 96.0,
        },
    )
    rule = MonitorRule(
        rule_id="r1", rule_type="crypto_funding_rate_gt", symbol="BTC", threshold=0.02
    )
    matches = MonitorService._match_crypto_funding_rate(_RuleStub(), rule)
    assert len(matches) == 1
    hit = matches[0]
    assert hit["symbol"] == "BTC"
    assert hit["payload"]["funding_rate_pct"] == 0.05
    assert hit["evidence"][2]["value"] == 96.0
    # 阈值以上 2 倍才算 high
    assert hit["severity"] == "high"


def test_monitor_funding_rate_rule_ignores_non_crypto_symbol(monkeypatch) -> None:
    from backend.app_services.monitor_service import MonitorService
    from backend.schemas import MonitorRule

    rule = MonitorRule(rule_id="r2", rule_type="crypto_funding_rate_gt", symbol="600519")
    assert MonitorService._match_crypto_funding_rate(_RuleStub(), rule) == []


def test_crypto_tasks_auto_seed_on_existing_install(tmp_path) -> None:
    """老安装升级时必须补上新默认任务，但用户删掉的旧任务不能被re-add。"""
    from backend.app_services.scheduler_service import CONFIG_KEY, DEFAULT_TASKS
    from tests.test_api import make_client

    client = make_client(tmp_path)
    svc = client.app.state.services if hasattr(client.app.state, "services") else None
    # 直接操作 config：模拟只有 A 股任务、且用户删掉了 weekly 的老安装
    import json as _json

    legacy = [
        dict(t)
        for t in DEFAULT_TASKS
        if t["task_id"] in {"sched_premarket", "sched_close", "sched_intraday"}
    ]
    repo = client.app.state.services.repo if svc else None
    assert repo is not None
    repo.set_config(CONFIG_KEY, {"items": legacy})

    items = client.get("/api/scheduled-tasks").json()["items"]
    ids = {t["task_id"] for t in items}
    # 新的加密货币任务被补上
    assert {"sched_crypto_daily", "sched_crypto_asia", "sched_crypto_late"} <= ids
    # 用户删掉的旧任务（weekly）不会被re-add
    assert "sched_weekly_review" not in ids
    # auto_seed 标记不会泄漏到存储里
    assert all("auto_seed" not in t for t in items)


# ── 11. P3：可靠性（FX 双源 + Gate 熔断）──────────────────
def test_fx_falls_back_to_secondary_source(monkeypatch) -> None:
    """主源挂 → 备源顶上，仍然不降级（degraded=False）。"""
    def primary_boom():
        raise RuntimeError("primary down")

    monkeypatch.setattr(fx, "_fetch_primary", primary_boom)
    monkeypatch.setattr(fx, "_fetch_fallback", lambda: (6.67, 7.8, "frankfurter.app"))
    fx.invalidate_cache()
    payload = fx.get_rates(refresh=True)
    assert payload["source"] == "frankfurter.app"
    assert payload["usd_cny"] == 6.67
    assert payload["degraded"] is False
    # 备源给的 1HKD=?CNY 由 USD 交叉汇率算出
    assert payload["hkd_cny"] == round(6.67 / 7.8, 6)
    fx.invalidate_cache()


def test_fx_degrades_when_both_sources_fail(monkeypatch) -> None:
    monkeypatch.setattr(fx, "_fetch_primary", lambda: (_ for _ in ()).throw(RuntimeError("a")))
    monkeypatch.setattr(fx, "_fetch_fallback", lambda: (_ for _ in ()).throw(RuntimeError("b")))
    fx.invalidate_cache()
    payload = fx.get_rates(refresh=True)
    assert payload["degraded"] is True
    assert payload["usd_cny"] is None
    assert fx.rates_for_conversion(payload) is None
    fx.invalidate_cache()


def test_gate_breaker_opens_after_threshold_failures(monkeypatch) -> None:
    """连续失败 3 次后熔断：第 4 次不再打源（对话不该每次等 5s 超时）。"""
    import httpx

    from backend.stock_domain import crypto_providers as cp

    cp.reset_breaker()
    calls = {"n": 0}
    real_get = httpx.get

    def failing_get(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "get", failing_get)
    try:
        for i in range(3):
            with pytest.raises(httpx.ConnectTimeout):
                cp.fetch_quote(f"X{i}")
        with pytest.raises(cp.CryptoSourceUnavailable):
            cp.fetch_quote("X9")
        assert calls["n"] == 3, f"熔断后不该再打源，实际打了 {calls['n']} 次"
        assert cp.breaker_state()["open"] is True
    finally:
        monkeypatch.setattr(httpx, "get", real_get)
        cp.reset_breaker()


# ── 12. P3：再平衡纳入加密（只给权重建议，不下单）──────────
def test_rebalance_draft_uses_converted_weight_and_marks_crypto(tmp_path, monkeypatch) -> None:
    from tests.test_api import make_client

    monkeypatch.setattr(
        fx,
        "_fetch_rates",
        lambda: {
            "as_of": "2026-10-24", "fetched_at": "2026-10-24T00:00:00+00:00",
            "source": "open.er-api.com", "usd_cny": 6.68, "hkd_cny": 0.86,
            "usdt_usd": 1.0, "degraded": False, "degraded_reason": None,
        },
    )
    fx.invalidate_cache()
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    client.post(
        "/api/holdings/import-confirm",
        json=[
            {"symbol": "600519", "name": "贵州茅台", "quantity": 100, "market_value": 100000, "weight_pct": 0, "cost": 1600},
            {"symbol": "BTC", "name": "Bitcoin", "quantity": 1, "market_value": 10000, "weight_pct": 0, "cost": 9000},
        ],
    )

    stock_draft = client.post(
        "/api/holdings/rebalance-draft", json={"symbol": "600519", "target_weight_pct": 30}
    ).json()
    crypto_draft = client.post(
        "/api/holdings/rebalance-draft", json={"symbol": "BTC", "target_weight_pct": 20}
    ).json()

    # 当前权重必须是折算后的真实占比（库里的 weight_pct 恒为 0）
    assert stock_draft["current_weight_pct"] > 50
    assert crypto_draft["current_weight_pct"] > 30
    # 股票可执行；加密货币不可执行，且标明资产类别
    assert stock_draft["executable"] is True
    assert stock_draft["asset_class"] == "stock"
    assert crypto_draft["executable"] is False
    assert crypto_draft["asset_class"] == "crypto"
    assert "权重建议" in crypto_draft["conclusion"]
    # 草案详情接口也要带这两个字段（前端卡片据此改文案）
    detail = client.get(f"/api/rebalance-drafts/{crypto_draft['draft_id']}").json()
    assert detail["executable"] is False
    assert detail["asset_class"] == "crypto"
    fx.invalidate_cache()

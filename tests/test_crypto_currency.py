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

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

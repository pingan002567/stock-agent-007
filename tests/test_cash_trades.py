"""买入扣现金、不可透支、卖出回钱、幂等、修正不动钱。"""
from __future__ import annotations

from tests.test_api import make_client


def _set_cash(client, amount, currency="CNY"):
    return client.post("/api/holdings/available-cash", json={"amount": amount, "currency": currency})


def _buy(client, **over):
    body = {
        "action": "buy", "symbol": "600963", "quantity": 100,
        "fill_price": 26.15, "fee": 5, "currency": "CNY",
    }
    body.update(over)
    return client.post("/api/holdings/trades", json=body)


def test_buy_deducts_cash_and_updates_holding(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 10000)

    resp = _buy(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 100 × 26.15 + 5 = 2620
    assert data["trade"]["cash_delta"] == -2620.0
    assert data["available_cash"] == 7380.0
    assert data["trade"]["quantity_after"] == 100.0

    # 现金流水有一条 buy
    ledger = client.get("/api/holdings/cash-ledger").json()
    assert any(row["reason"] == "buy" and row["delta"] == -2620.0 for row in ledger["items"])


def test_buy_rejected_when_cash_not_enough(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 1000)

    resp = _buy(client)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "insufficient_cash"
    assert detail["available"] == 1000.0
    assert detail["shortfall"] == 1620.0

    # 关键：被拒时**不能**留下半截持仓
    holdings = client.get("/api/holdings").json()
    assert all(item["symbol"] != "600963" for item in holdings["items"])
    assert holdings["summary"]["available_cash"] == 1000.0


def test_buy_rejected_when_cash_never_recorded(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")

    resp = _buy(client)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cash_not_recorded"


def test_sell_returns_cash_and_blocks_oversell(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 10000)
    _buy(client)

    over = client.post("/api/holdings/trades", json={
        "action": "sell", "symbol": "600963", "quantity": 200, "fill_price": 27, "currency": "CNY",
    })
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "insufficient_holding"

    sold = client.post("/api/holdings/trades", json={
        "action": "sell", "symbol": "600963", "quantity": 100, "fill_price": 27, "fee": 5, "currency": "CNY",
    })
    assert sold.status_code == 200
    assert sold.json()["available_cash"] == 7380 + 2695  # 27*100 - 5


def test_idempotent_replay_does_not_double_charge(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 10000)

    first = _buy(client, idempotency_key="order-1").json()
    second = _buy(client, idempotency_key="order-1").json()
    assert second["trade"]["replayed"] is True
    assert second["available_cash"] == first["available_cash"] == 7380.0


def test_multi_currency_buckets_are_separate(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 1000, "CNY")
    _set_cash(client, 500, "USDT")

    # 买 BTC 扣 USDT，不动 CNY
    resp = client.post("/api/holdings/trades", json={
        "action": "buy", "symbol": "BTC", "quantity": 0.01, "fill_price": 30000, "currency": "USDT",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["available_cash"] == 200.0
    summary = resp.json()["summary"]
    cash = {row["currency"]: row["amount"] for row in summary["cash_by_currency"]}
    assert cash["CNY"] == 1000.0 and cash["USDT"] == 200.0


def test_correction_api_does_not_touch_cash(tmp_path):
    """`POST /api/holdings` 是"修正持仓"，不能扣钱（导入/纠错都走它）。"""
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    _set_cash(client, 5000)

    resp = client.post("/api/holdings", json={"symbol": "600963", "quantity": 100, "cost": 26.15})
    assert resp.status_code == 200
    assert resp.json()["summary"]["available_cash"] == 5000.0


def test_calibrate_multiple_currencies_writes_adjust_entries(tmp_path):
    """一键校准：多个币种一次性写入，每个币种一条 adjust 流水。"""
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")

    resp = client.post("/api/holdings/cash-calibration", json={
        "amounts": {"CNY": 12345.68, "USDT": 500, "USD": 0},
        "note": "对券商实况校准",
    })
    assert resp.status_code == 200, resp.text
    buckets = resp.json()["cash_by_currency"]
    assert buckets == {"CNY": 12345.68, "USDT": 500.0, "USD": 0.0}

    ledger = client.get("/api/holdings/cash-ledger").json()
    adjusts = [row for row in ledger["items"] if row["reason"] == "adjust"]
    assert {row["currency"] for row in adjusts} == {"CNY", "USDT", "USD"}
    assert all("对券商实况校准" in (row["note"] or "") for row in adjusts)


def test_calibrate_rejects_negative_and_keeps_untouched(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/holdings/clear-demo")
    client.post("/api/holdings/cash-calibration", json={"amounts": {"CNY": 1000}})

    bad = client.post("/api/holdings/cash-calibration", json={"amounts": {"CNY": -1}})
    assert bad.status_code == 400
    assert client.get("/api/holdings/cash-ledger").json()["cash_by_currency"]["CNY"] == 1000.0

    # 只校准 USDT，CNY 保持不变
    client.post("/api/holdings/cash-calibration", json={"amounts": {"USDT": 200}})
    buckets = client.get("/api/holdings/cash-ledger").json()["cash_by_currency"]
    assert buckets["CNY"] == 1000.0 and buckets["USDT"] == 200.0

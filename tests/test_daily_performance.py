"""盘后表现：日K口径的今日收益、贡献、基准、回撤、距成本。"""
from __future__ import annotations

from datetime import date

from tests.test_api import make_client


def _stub_kline(monkeypatch, rows):
    """rows: symbol -> [(date, close), ...]（升序）"""
    from backend.stock_domain import performance_tools as perf

    def fake(symbol, days=3):
        data = rows.get(symbol)
        if not data:
            return {"items": []}
        return {"items": [{"date": d, "close": c} for d, c in data]}

    monkeypatch.setattr(perf, "_last_two_closes", lambda symbol: (
        (lambda pairs: (pairs[-1][1], pairs[-2][1], pairs[-1][0].replace("-", "")))(rows[symbol])
        if rows.get(symbol) and len(rows[symbol]) >= 2 else None
    ))


def test_daily_performance_uses_daily_close(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    services = client.app.state.services
    repo = services.repo
    client.post("/api/holdings/clear-demo")

    from backend.schemas import HoldingPosition
    repo.upsert_holding(HoldingPosition(
        symbol="000963", name="华东医药", quantity=100, market_value=2656.0,
        weight_pct=0, cost=26.74, currency="CNY",
    ))
    client.post("/api/holdings/available-cash", json={"amount": 2962.53, "currency": "CNY"})

    _stub_kline(monkeypatch, {"000963": [("2026-11-10", 26.87), ("2026-11-11", 26.56)]})

    resp = client.get("/api/holdings/performance")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    p = data["portfolio"]
    # (26.56 - 26.87) × 100 = -31
    assert p["day_pnl"] == -31.0
    assert round(p["prev_nav"], 2) == round(26.87 * 100 + 2962.53, 2)
    assert p["day_return_pct"] is not None and p["day_return_pct"] < 0
    # 距成本：26.56 / 26.74 - 1 = -0.67%
    assert data["distance_to_cost"][0]["pnl_pct"] == -0.67
    assert data["contributors"]["negative"][0]["symbol"] == "000963"


def test_drawdown_uses_nav_snapshot_series(tmp_path):
    client = make_client(tmp_path)
    repo = client.app.state.services.repo
    repo.upsert_nav_snapshot("2026-11-01", 10000.0, 8000.0, 2000.0)
    repo.upsert_nav_snapshot("2026-11-05", 12000.0, 9000.0, 3000.0)
    assert repo.peak_nav() == 12000.0
    # 当天净值写入后应能得到回撤
    data = client.get("/api/holdings/performance").json()
    assert data["portfolio"]["peak_nav"] is not None
    assert data["portfolio"]["drawdown_pct"] is not None
    assert data["portfolio"]["drawdown_pct"] <= 0

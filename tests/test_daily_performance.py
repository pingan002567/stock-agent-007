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


def test_triage_splits_must_handle_from_noise(tmp_path, monkeypatch):
    """17 条待办不能全列：高优先/高严重度进 must_handle，其余只计数。"""
    client = make_client(tmp_path)
    services = client.app.state.services

    from types import SimpleNamespace

    inbox = [
        SimpleNamespace(item_key="a", status="open", priority="high", title="医保降价", item_type="intel"),
        SimpleNamespace(item_key="b", status="open", priority="medium", title="普通提醒", item_type="intel"),
        SimpleNamespace(item_key="c", status="done", priority="high", title="已完成", item_type="intel"),
    ]
    events = [
        SimpleNamespace(event_id="e1", severity="high", title="跌破止损", symbol="000963"),
        SimpleNamespace(event_id="e2", severity="low", title="常规波动", symbol="600977"),
    ]
    monkeypatch.setattr(services.review_inbox_service, "list_items", lambda **kw: inbox)
    monkeypatch.setattr(services.monitor_service, "list_events", lambda **kw: events)

    from backend.stock_domain.performance_tools import build_triage

    triage = build_triage(services)
    assert triage["counts"] == {"inbox_open": 2, "inbox_high": 1, "monitor_events": 2, "monitor_high": 1}
    assert triage["must_count"] == 2
    assert {row["kind"] for row in triage["must_handle"]} == {"inbox", "monitor"}
    assert triage["can_ignore_count"] == 2  # 1 条普通待办 + 1 条低严重度事件


def test_missing_today_bar_reports_unknown_not_yesterday(tmp_path, monkeypatch):
    """15:15 跑报告时今日日K可能还没落地：今日收益必须为 None，不能拿昨天的充数。"""
    from datetime import date

    client = make_client(tmp_path)
    services = client.app.state.services
    client.post("/api/holdings/clear-demo")
    from backend.schemas import HoldingPosition
    services.repo.upsert_holding(HoldingPosition(
        symbol="000963", name="华东医药", quantity=100, market_value=2656.0,
        weight_pct=0, cost=26.74, currency="CNY",
    ))

    from backend.stock_domain import performance_tools as perf

    # 最新一根是昨天 → 与 expected_bar 不符
    monkeypatch.setattr(perf, "_last_two_closes", lambda symbol: (26.87, 27.05, "20260101"))
    monkeypatch.setattr(perf, "expected_bar_date", lambda market: date(2026, 11, 11))

    data = client.get("/api/holdings/performance").json()
    assert data["portfolio"]["day_pnl"] is None
    assert data["portfolio"]["day_return_pct"] is None
    assert data["portfolio"]["day_pnl_available"] is False
    assert "today_bar_missing" in data["data_health"]["price_basis"]

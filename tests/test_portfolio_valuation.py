from fastapi.testclient import TestClient

from backend.app import create_app
from backend.schemas import HoldingPosition, PriceSnapshot
from backend.stock_domain.portfolio_tools import mark_to_market


def test_mark_to_market_uses_live_price():
    item = HoldingPosition(
        symbol="000963",
        name="华东医药",
        quantity=100,
        cost=26.74,
        market_value=2674,
        weight_pct=0,
    )
    market_value, pnl_amount, pnl_pct = mark_to_market(item, 30)
    assert market_value == 3000
    assert pnl_amount == 326
    assert pnl_pct == 12.19


def test_mark_to_market_stays_blank_when_price_missing_and_value_is_cost():
    item = HoldingPosition(
        symbol="002467",
        name="二六三",
        quantity=100,
        cost=4.87,
        market_value=487,
        weight_pct=0,
    )
    market_value, pnl_amount, pnl_pct = mark_to_market(item, None)
    assert market_value == 487
    assert pnl_amount is None
    assert pnl_pct is None


def test_mark_to_market_uses_stored_value_when_it_differs_from_cost():
    item = HoldingPosition(
        symbol="000963",
        name="华东医药",
        quantity=100,
        cost=26.74,
        market_value=3000,
        weight_pct=0,
    )
    market_value, pnl_amount, pnl_pct = mark_to_market(item, None)
    assert market_value == 3000
    assert pnl_amount == 326
    assert pnl_pct == 12.19


def test_holdings_api_fills_pnl_from_quote(tmp_path, monkeypatch):
    def fake_quote(symbol: str, force: bool = False) -> PriceSnapshot:
        last = 27.29 if "000963" in symbol else 5.2
        return PriceSnapshot(
            last=last,
            change_pct=1.26 if "000963" in symbol else 0.97,
            updated_at="2026-10-09T07:00:00+00:00",
            source="test",
            degraded=False,
        )

    monkeypatch.setattr(
        "backend.stock_domain.provider_router.provider_router.get_quote",
        fake_quote,
    )
    app = create_app(db_path=tmp_path / "api.sqlite3", files_root=tmp_path / "files")
    repo = app.state.services.repo
    repo.clear_demo_portfolio()
    repo.upsert_holding(HoldingPosition(
        symbol="000963", name="华东医药", quantity=100, cost=26.74,
        market_value=2674, weight_pct=0,
    ))
    repo.upsert_holding(HoldingPosition(
        symbol="002467", name="二六三", quantity=100, cost=4.87,
        market_value=487, weight_pct=0,
    ))
    data = TestClient(app).get("/api/holdings").json()
    by_symbol = {item["symbol"]: item for item in data["items"]}
    huadong = by_symbol["000963"]
    erliu = by_symbol["002467"]
    assert huadong["market_value"] == 2729
    assert huadong["pnl_amount"] == 55
    assert huadong["pnl_pct"] == 2.06
    assert erliu["market_value"] == 520
    assert erliu["pnl_amount"] == 33
    assert erliu["pnl_pct"] == 6.78
    assert data["summary"]["market_value"] == 3249

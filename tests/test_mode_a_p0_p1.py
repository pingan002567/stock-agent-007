"""P0/P1: Mode A recovery hints, warmup gate, financial sqlite cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.agent_runtime.prompt_envelope import LEAD_RUNTIME_CONSTRAINTS, render_prompt_envelope
from backend.schemas import StockFinancial, now_iso
from backend.stock_domain.capability_invoke import invoke_data_capability
from backend.stock_domain.industry_tools import _mode_a_industry_recovery, get_industry_context
from backend.stock_domain.provider_router import provider_router, should_run_market_warmup


def test_lead_constraints_require_mode_a_on_degraded():
    blob = "\n".join(LEAD_RUNTIME_CONSTRAINTS)
    assert "invoke_data_capability" in blob
    assert "degraded" in blob
    assert "tonghuashun" in blob or "list_data_sources" in blob
    rendered = render_prompt_envelope(user_message="测一下")
    assert "invoke_data_capability" in rendered
    assert "Mode B" in rendered or "自选/持仓" in rendered


def test_industry_degraded_includes_mode_a_recovery(monkeypatch):
    from backend.stock_domain import industry_tools

    monkeypatch.setattr(industry_tools, "_cached_boards", lambda: [])
    monkeypatch.setattr(industry_tools, "_cached_constituents", lambda industry: [])
    industry_tools._BOARDS_CACHE.clear()
    industry_tools._CONS_CACHE.clear()

    out = get_industry_context(industry="白酒")
    assert out["degraded"] is True
    recovery = out["mode_a_recovery"]
    assert recovery["required"] is True
    assert recovery["steps"][0]["tool"] == "list_data_sources"
    assert any(
        s.get("provider") == "tonghuashun" and s.get("capability") == "industry_boards"
        for s in recovery["steps"]
    )
    hint = _mode_a_industry_recovery("白酒")
    assert hint["steps"][-1]["params"]["industry"] == "白酒"


def test_eastmoney_industry_fail_then_tonghuashun_invoke(monkeypatch):
    """Deterministic: when EM boards empty, Mode A tonghuashun boards still work."""
    from backend.stock_domain import capability_invoke as ci

    monkeypatch.setattr(ci, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(ci, "is_provider_usable", lambda config, pid: True)
    monkeypatch.setattr(
        "backend.stock_domain.industry_tools._boards_from_ths",
        lambda: [{"industry": "白酒", "change_pct": 1.0, "source": "ths"}],
    )
    # Force EM path empty via create_provider mock for eastmoney
    class _Empty:
        name = "eastmoney"

        def fetch_industry_boards(self):
            return []

        def is_available(self):
            return True

    monkeypatch.setattr(ci, "create_provider", lambda pid: _Empty() if pid == "eastmoney" else type("P", (), {"name": pid})())
    em = invoke_data_capability("eastmoney", "industry_boards", {})
    assert em["ok"] is True  # falls back to ths inside _invoke_industry_boards
    assert em["data"]["count"] >= 1

    ths = invoke_data_capability("tonghuashun", "industry_boards", {})
    assert ths["ok"] is True
    assert ths["data"]["items"][0]["industry"] == "白酒"


def test_should_run_market_warmup_skips_weekend():
    saturday = datetime(2026, 9, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # Sat
    assert should_run_market_warmup(saturday) is False
    # Monday mid-session
    monday = datetime(2026, 9, 14, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    # May be holiday-aware; if calendar says trading, expect True
    from backend.stock_domain.trading_calendar import is_trading_day

    if is_trading_day("CN", monday.date()):
        assert should_run_market_warmup(monday) is True
    night = datetime(2026, 9, 14, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert should_run_market_warmup(night) is False


def test_financial_reads_sqlite_within_ttl(tmp_path, monkeypatch):
    from backend.bootstrap import create_services

    services = create_services(db_path=tmp_path / "fin.sqlite3", files_root=tmp_path / "files")
    provider_router.repo = services.repo
    # Clear mem cache
    provider_router._mem_cache.invalidate_prefix("financial:")

    services.repo.upsert_stock_financial(
        StockFinancial(
            symbol="600519",
            report_date="2025-12-31",
            report_type="annual",
            revenue=1e11,
            profit=5e10,
            total_assets=2e11,
            total_liabilities=5e10,
            payload={"source": "test_seed"},
            created_at=now_iso(),
        )
    )

    # Network must not be required
    def _boom(*a, **k):
        raise AssertionError("should not call network for fresh sqlite financial")

    monkeypatch.setattr(provider_router, "_call_with_provider", _boom)
    payload = provider_router.get_financial("600519")
    assert payload["degraded"] is False
    assert payload["coverage"]["mode"] == "persisted"
    assert payload["items"][0]["revenue"] == 1e11

    # Expire by rewriting created_at far in the past
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    services.repo.upsert_stock_financial(
        StockFinancial(
            symbol="600519",
            report_date="2025-12-31",
            report_type="annual",
            revenue=1e11,
            profit=5e10,
            total_assets=2e11,
            total_liabilities=5e10,
            payload={"source": "test_seed"},
            created_at=old,
        )
    )
    provider_router._mem_cache.invalidate_prefix("financial:")
    called = {"n": 0}

    def _fake_call(capability, provider, market, call_fn, symbol=""):
        called["n"] += 1
        return {
            "symbol": "600519",
            "degraded": False,
            "source": "network",
            "items": [{"report_date": "2025-12-31", "revenue": 2e11, "profit": 1, "total_assets": 1, "total_liabilities": 1}],
        }

    monkeypatch.setattr(provider_router, "_call_with_provider", _fake_call)
    monkeypatch.setattr(provider_router, "_provider_for_market", lambda market: object())
    fresh = provider_router.get_financial("600519")
    assert called["n"] == 1
    assert fresh["source"] == "network"

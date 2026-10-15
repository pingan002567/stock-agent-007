"""Industry name resolution + degrade hints (no network)."""

from __future__ import annotations

from backend.stock_domain.industry_tools import (
    _boards_from_master,
    _constituents_from_master,
    resolve_industry_name,
)


def test_resolve_industry_name_exact_and_suffix():
    boards = ["化学制药", "生物制品", "中药", "白酒"]
    assert resolve_industry_name("化学制药", boards) == "化学制药"
    assert resolve_industry_name("化学制药行业", boards) == "化学制药"
    assert resolve_industry_name("生物制品板块", boards) == "生物制品"


def test_resolve_industry_name_substring_unique():
    boards = ["化学制药", "化学原料", "白酒"]
    assert resolve_industry_name("制药", boards) == "化学制药"


def test_resolve_industry_name_miss_returns_none():
    assert resolve_industry_name("不存在的板块", ["化学制药", "白酒"]) is None
    assert resolve_industry_name("", ["化学制药"]) is None


def test_boards_from_master_uses_distinct_industries(monkeypatch):
    class _Stock:
        def __init__(self, symbol, industry, market="CN"):
            self.symbol = symbol
            self.name = symbol
            self.industry = industry
            self.market = market

    class _Repo:
        def list_stock_master(self, *, active_only=True):
            return [
                _Stock("600519", "酿酒行业"),
                _Stock("000858", "酿酒行业"),
                _Stock("AAPL", "Software", "US"),
                _Stock("300750", "电池"),
            ]

    monkeypatch.setattr(
        "backend.stock_domain.industry_tools.provider_router.repo",
        _Repo(),
    )
    boards = _boards_from_master()
    names = {b["industry"] for b in boards}
    assert names == {"酿酒行业", "电池"}
    assert all(b.get("source") == "stock_master" for b in boards)


def test_constituents_from_master_without_spot(monkeypatch):
    class _Stock:
        def __init__(self, symbol, name, industry, market="CN"):
            self.symbol = symbol
            self.name = name
            self.industry = industry
            self.market = market

    class _Repo:
        def list_stock_master(self, *, active_only=True):
            return [
                _Stock("600519", "贵州茅台", "酿酒行业"),
                _Stock("000858", "五粮液", "酿酒行业"),
                _Stock("300750", "宁德时代", "电池"),
            ]

    class _Primary:
        def _cached(self, *args, **kwargs):
            raise RuntimeError("spot unavailable")

        def _load_cn_spot(self):
            return None

        def _ak(self):
            raise RuntimeError("no ak")

    monkeypatch.setattr(
        "backend.stock_domain.industry_tools.provider_router.repo",
        _Repo(),
    )
    monkeypatch.setattr(
        "backend.stock_domain.industry_tools._akshare_primary",
        lambda: _Primary(),
    )
    rows = _constituents_from_master("酿酒行业")
    assert {r["symbol"] for r in rows} == {"600519", "000858"}
    assert all(r.get("source") == "stock_master+spot" for r in rows)

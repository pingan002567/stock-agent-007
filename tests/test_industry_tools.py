"""Industry name resolution + degrade hints (no network)."""

from __future__ import annotations

from backend.stock_domain.industry_tools import resolve_industry_name


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

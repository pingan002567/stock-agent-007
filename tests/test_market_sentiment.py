"""情绪数据工具的纯聚合测试（不联网：monkeypatch 掉两个取数函数）。

工具只做聚合（计数/排序/比值），不做判断（温度分/阶段）——判断交给模型。
"""

from __future__ import annotations

import pytest

from backend.stock_domain import sentiment_tools


def _pool_fixture(name: str, day: str):
    if name == "stock_zt_pool_em":
        return [
            {"代码": "003029", "名称": "吉大正元", "连板数": 4, "封板资金": 2.0e8, "所属行业": "IT服务Ⅱ"},
            {"代码": "002835", "名称": "同为股份", "连板数": 2, "封板资金": 1.0e8, "所属行业": "IT服务Ⅱ"},
            {"代码": "600661", "名称": "昂立教育", "连板数": 2, "封板资金": 0.5e8, "所属行业": "教育"},
            {"代码": "000001", "名称": "平安银行", "连板数": 1, "封板资金": 0.1e8, "所属行业": "银行"},
        ], None
    if name == "stock_zt_pool_zbgc_em":
        return [{"代码": "600000"}, {"代码": "600001"}], None
    if name == "stock_zt_pool_previous_em":
        return [{"涨跌幅": 3.1}, {"涨跌幅": 1.2}, {"涨跌幅": -2.0}, {"涨跌幅": 0.4}], None
    if name == "stock_zt_pool_dtgc_em":
        return [{"代码": "300001"}], None
    raise AssertionError(f"unexpected pool {name}")


def _breadth_fixture():
    return {
        "rising": 3000,
        "falling": 1800,
        "flat": 100,
        "sample_size": 4900,
        "turnover": 1.2e12,
        "source": "eastmoney",
    }, None


@pytest.fixture()
def data(monkeypatch):
    monkeypatch.setattr(sentiment_tools, "_pool", _pool_fixture)
    monkeypatch.setattr(sentiment_tools, "_breadth", _breadth_fixture)
    return sentiment_tools.get_market_sentiment()


def test_no_judgment_fields(data) -> None:
    """工具不该产出温度分/阶段/公式这些结论字段。"""
    assert "temperature" not in data
    assert "phase" not in data
    assert "score_parts" not in data
    assert "formula" not in data
    assert "divergence" not in data


def test_ladder_and_counts(data) -> None:
    lu = data["limit_up"]
    assert lu["count"] == 4
    assert lu["max_streak"] == 4
    assert lu["ladder"] == {"4板": 1, "2板": 2, "1板": 1}
    # 同一行业 ≥3 家才算抱团；这里 IT服务Ⅱ 只有 2 家 → 不进 hot_sectors
    assert all(item["count"] >= 3 for item in lu["hot_sectors"])


def test_broken_rate_and_red_ratio(data) -> None:
    assert data["broken"]["count"] == 2
    assert data["broken"]["rate"] == pytest.approx(2 / 6, abs=1e-4)
    assert data["previous_limit_up"]["red_count"] == 3
    assert data["previous_limit_up"]["red_ratio"] == pytest.approx(0.75, abs=1e-4)


def test_sealed_top_sorted_by_sealed(data) -> None:
    top = data["limit_up"]["sealed_amount_top"]
    assert len(top) == 4
    assert top[0]["symbol"] == "003029"  # 封板资金最大
    assert [x["sealed"] for x in top] == sorted([x["sealed"] for x in top], reverse=True)


def test_degraded_when_all_fail(monkeypatch) -> None:
    monkeypatch.setattr(sentiment_tools, "_pool", lambda name, day: ([], f"{name}: boom"))
    monkeypatch.setattr(sentiment_tools, "_breadth", lambda: ({}, "market_review: boom"))
    r = sentiment_tools.get_market_sentiment()
    assert r["degraded"] is True
    assert set(r["coverage"]["missing"]) >= {
        "limit_up_pool", "broken_pool", "previous_limit_up", "limit_down_pool", "breadth",
    }
    # 数据缺失就缺失，不产出"冰点 0 分"这种假结论
    assert "temperature" not in r

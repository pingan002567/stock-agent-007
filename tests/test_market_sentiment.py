"""情绪温度计的纯逻辑测试（不联网：monkeypatch 掉两个取数函数）。"""

from __future__ import annotations

import pytest

from backend.stock_domain import sentiment_tools


def _pool_fixture(name: str, day: str):
    """按池名返回固定数据。"""
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
def strong_market(monkeypatch):
    monkeypatch.setattr(sentiment_tools, "_pool", _pool_fixture)
    monkeypatch.setattr(sentiment_tools, "_breadth", _breadth_fixture)
    return sentiment_tools.get_market_sentiment()


def test_ladder_and_counts(strong_market) -> None:
    lu = strong_market["limit_up"]
    assert lu["count"] == 4
    assert lu["max_streak"] == 4
    assert lu["ladder"] == {"4板": 1, "2板": 2, "1板": 1}
    # 同一行业 ≥3 家才算抱团；这里 IT服务Ⅱ 只有 2 家
    assert all(item["count"] >= 3 for item in lu["hot_sectors"])


def test_broken_rate_and_red_ratio(strong_market) -> None:
    # 炸板率 = 炸板 / (涨停 + 炸板) = 2 / 6
    assert strong_market["broken"]["count"] == 2
    assert strong_market["broken"]["rate"] == pytest.approx(2 / 6, abs=1e-4)
    # 昨日涨停 4 家，今日红盘 3 家
    assert strong_market["previous_limit_up"]["red_count"] == 3
    assert strong_market["previous_limit_up"]["red_ratio"] == pytest.approx(0.75, abs=1e-4)


def test_temperature_and_phase(strong_market) -> None:
    t = strong_market["temperature"]
    assert t is not None and 0 <= t <= 100
    # 涨停 4 家/最高 4 板/涨跌比健康/炸板率 33%/红盘率 75% —— 不应判成冰点
    assert strong_market["phase"] in {"修复", "升温", "高潮"}
    assert strong_market["divergence"] is None


def _many_limit_up(n: int = 40):
    """构造 n 家涨停（背离判定要求涨停数 ≥30）。"""
    rows = [
        {"代码": f"{600000 + i}", "名称": f"票{i}", "连板数": 1 + (i % 3), "封板资金": 1.0e8, "所属行业": "IT服务Ⅱ"}
        for i in range(n)
    ]
    return lambda name, day: (rows, None) if name == "stock_zt_pool_em" else ([], None)


def test_divergence_guard_caps_phase(monkeypatch) -> None:
    """涨停多但全市场普跌 → 必须封顶到分化，并给出文字说明。"""
    monkeypatch.setattr(sentiment_tools, "_pool", _many_limit_up(40))
    monkeypatch.setattr(
        sentiment_tools,
        "_breadth",
        lambda: (
            {"rising": 300, "falling": 4000, "flat": 50, "sample_size": 4350, "turnover": 8e11, "source": "eastmoney"},
            None,
        ),
    )
    r = sentiment_tools.get_market_sentiment()
    assert r["phase"] == "分化"
    assert r["temperature"] <= 55.0
    assert r["divergence"] and "结构性分化" in r["divergence"]


def test_degraded_when_pools_fail(monkeypatch) -> None:
    """所有池都拉不到时必须降级，且不给温度分（0 分会被误读成冰点）。"""
    monkeypatch.setattr(sentiment_tools, "_pool", lambda name, day: ([], f"{name}: boom"))
    monkeypatch.setattr(sentiment_tools, "_breadth", lambda: ({}, "market_review: boom"))
    r = sentiment_tools.get_market_sentiment()
    assert r["degraded"] is True
    assert r["temperature"] is None
    assert r["phase"] == "未知"
    assert set(r["coverage"]["missing"]) >= {
        "limit_up_pool", "broken_pool", "previous_limit_up", "limit_down_pool", "breadth",
    }

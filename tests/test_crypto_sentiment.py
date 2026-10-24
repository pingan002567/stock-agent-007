"""加密货币全市场情绪的纯聚合测试（不联网：monkeypatch 掉 `_get_json`）。

覆盖三件事：
1. 三个源各自独立降级（一个挂不影响其它字段，且不抛异常）；
2. 缺数据返回 None，不拿 0 冒充；
3. 恐慌贪婪中文分档边界 + 工具层 market 分发。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.agent_runtime.tool_bridge import WorkbenchToolBridge
from backend.stock_domain import crypto_sentiment, sentiment_tools

GLOBAL_PAYLOAD = [
    {
        "total_mcap": 2_350_000_000_000.0,
        "total_volume": 81_000_000_000.0,
        "mcap_change": -1.25,
        "btc_d": "60.23",
        "eth_d": "9.81",
        "coins_count": 12_345,
    }
]

STABLECOIN_PAYLOAD = {
    "peggedAssets": [
        {"circulating": {"peggedUSD": 100_000_000_000.0}},
        {"circulating": {"peggedUSD": 50_000_000_000.0}},
        {"circulating": {}},  # 缺字段：跳过，不当 0 累加
        {"circulating": {"peggedUSD": None}},
    ]
}

FEAR_GREED_PAYLOAD = {
    "data": [
        {"value": "51", "value_classification": "Neutral", "timestamp": "1789000000"},
        {"value": "45", "value_classification": "Fear", "timestamp": "1788913600"},
    ]
}


def _fake_get_json(url: str):
    if url.startswith("https://api.coinlore.net/"):
        return GLOBAL_PAYLOAD
    if url.startswith("https://stablecoins.llama.fi/"):
        return STABLECOIN_PAYLOAD
    if url.startswith("https://api.alternative.me/"):
        return FEAR_GREED_PAYLOAD
    raise AssertionError(f"unexpected url {url}")


@pytest.fixture(autouse=True)
def _clean_cache():
    crypto_sentiment.invalidate_cache()
    yield
    crypto_sentiment.invalidate_cache()


@pytest.fixture()
def data(monkeypatch):
    monkeypatch.setattr(crypto_sentiment, "_get_json", _fake_get_json)
    return crypto_sentiment.get_crypto_market_sentiment()


def test_all_sources_ok(data) -> None:
    assert data["market"] == "CRYPTO"
    assert data["total_market_cap_usd"] == pytest.approx(2.35e12)
    assert data["total_volume_24h_usd"] == pytest.approx(8.1e10)
    assert data["market_cap_change_24h_pct"] == pytest.approx(-1.25)
    assert data["btc_dominance_pct"] == pytest.approx(60.23)
    assert data["eth_dominance_pct"] == pytest.approx(9.81)
    assert data["stablecoin_total_usd"] == pytest.approx(1.5e11)
    # 51 → Neutral → 中性；前值取第二条
    assert data["fear_greed"] == {
        "value": 51,
        "label_en": "Neutral",
        "label_zh": "中性",
        "previous": 45,
    }
    assert data["degraded"] is False
    assert data["degraded_reason"] is None
    assert {k: v["status"] for k, v in data["coverage"].items()} == {
        "coinlore": "ok",
        "defillama": "ok",
        "alternative_me": "ok",
    }
    assert data["sources"] == {
        "market": "coinlore",
        "stablecoin": "defillama",
        "fear_greed": "alternative.me",
    }
    datetime.fromisoformat(data["as_of"])  # ISO 时间可解析


def test_fear_greed_failure_is_isolated(monkeypatch) -> None:
    """恐贪源挂掉：其它字段照常，只标记自己 failed，且不抛异常。"""

    def _flaky(url: str):
        if url.startswith("https://api.alternative.me/"):
            raise TimeoutError("boom")
        return _fake_get_json(url)

    monkeypatch.setattr(crypto_sentiment, "_get_json", _flaky)
    result = crypto_sentiment.get_crypto_market_sentiment()

    assert result["total_market_cap_usd"] == pytest.approx(2.35e12)
    assert result["stablecoin_total_usd"] == pytest.approx(1.5e11)
    assert result["fear_greed"] == {
        "value": None,
        "label_en": None,
        "label_zh": None,
        "previous": None,
    }
    assert result["degraded"] is True
    assert "alternative.me" in result["degraded_reason"]
    assert result["coverage"]["alternative_me"]["status"] == "failed"
    assert result["coverage"]["coinlore"]["status"] == "ok"
    assert result["coverage"]["defillama"]["status"] == "ok"


def test_coinlore_failure_is_isolated(monkeypatch) -> None:
    """市值源挂掉：五个市值/主导率字段全 None，其它源照常。"""

    def _flaky(url: str):
        if url.startswith("https://api.coinlore.net/"):
            raise ConnectionError("boom")
        return _fake_get_json(url)

    monkeypatch.setattr(crypto_sentiment, "_get_json", _flaky)
    result = crypto_sentiment.get_crypto_market_sentiment()

    for key in (
        "total_market_cap_usd",
        "total_volume_24h_usd",
        "market_cap_change_24h_pct",
        "btc_dominance_pct",
        "eth_dominance_pct",
    ):
        assert result[key] is None
    assert result["stablecoin_total_usd"] == pytest.approx(1.5e11)
    assert result["fear_greed"]["value"] == 51
    assert result["degraded"] is True
    assert result["coverage"]["coinlore"]["status"] == "failed"
    assert result["coverage"]["alternative_me"]["status"] == "ok"


def test_empty_stablecoin_list_yields_none_not_zero(monkeypatch) -> None:
    """稳定币空列表 = 总量未知，必须是 None 而不是 0。"""

    def _empty_stable(url: str):
        if url.startswith("https://stablecoins.llama.fi/"):
            return {"peggedAssets": []}
        return _fake_get_json(url)

    monkeypatch.setattr(crypto_sentiment, "_get_json", _empty_stable)
    result = crypto_sentiment.get_crypto_market_sentiment()

    assert result["stablecoin_total_usd"] is None
    assert result["stablecoin_total_usd"] != 0
    assert result["coverage"]["defillama"]["status"] == "failed"
    assert result["degraded"] is True
    # 其它源不受影响
    assert result["total_market_cap_usd"] == pytest.approx(2.35e12)
    assert result["fear_greed"]["value"] == 51


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (0, "极度恐惧"),
        (24, "极度恐惧"),
        (25, "恐惧"),
        (44, "恐惧"),
        (45, "中性"),
        (55, "中性"),
        (56, "贪婪"),
        (75, "贪婪"),
        (76, "极度贪婪"),
        (100, "极度贪婪"),
    ],
)
def test_fear_greed_label_boundaries(value: int, label: str) -> None:
    assert crypto_sentiment._fear_greed_label_zh(value) == label


def test_cache_ttl_and_invalidate(monkeypatch) -> None:
    calls: list[str] = []

    def _counting(url: str):
        calls.append(url)
        return _fake_get_json(url)

    monkeypatch.setattr(crypto_sentiment, "_get_json", _counting)
    crypto_sentiment.get_crypto_market_sentiment()
    crypto_sentiment.get_crypto_market_sentiment()
    assert len(calls) == 3  # 第二次命中缓存，不再打源
    crypto_sentiment.invalidate_cache()
    crypto_sentiment.get_crypto_market_sentiment()
    assert len(calls) == 6


def _stub_sentiment(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        crypto_sentiment,
        "get_crypto_market_sentiment",
        lambda: calls.append("crypto") or {"market": "CRYPTO"},
    )
    monkeypatch.setattr(
        sentiment_tools,
        "get_market_sentiment",
        lambda: calls.append("a_share") or {"market": "A股"},
    )
    # handler 只用 arguments，不碰实例属性
    bridge = WorkbenchToolBridge.__new__(WorkbenchToolBridge)
    return bridge, calls


def test_bridge_routes_market_crypto(monkeypatch) -> None:
    bridge, calls = _stub_sentiment(monkeypatch)

    assert bridge._get_market_sentiment({"market": "CRYPTO"}) == {"market": "CRYPTO"}
    assert bridge._get_market_sentiment({"market": "crypto"}) == {"market": "CRYPTO"}
    assert bridge._get_market_sentiment({"market": "币"}) == {"market": "CRYPTO"}
    assert calls == ["crypto", "crypto", "crypto"]


def test_bridge_defaults_to_a_share(monkeypatch) -> None:
    bridge, calls = _stub_sentiment(monkeypatch)

    assert bridge._get_market_sentiment({}) == {"market": "A股"}
    assert bridge._get_market_sentiment({"market": ""}) == {"market": "A股"}
    assert bridge._get_market_sentiment({"market": "A股"}) == {"market": "A股"}
    assert calls == ["a_share", "a_share", "a_share"]


# ── native schema 覆盖：wrapper 不存在时模型根本看不见工具 ──
def test_native_wrappers_registered() -> None:
    """`get_market_sentiment` / `get_crypto_derivatives` 必须有 StructuredTool wrapper。

    只在 tool_bridge 里注册是不够的：模型侧 schema 来自 tools.py 的 wrapper，
    缺了就会出现「prompt 说必须调用，但工具列表里没有」的哑火。
    """
    from backend.agent_runtime.deerflow_config import TOOL_GROUP_MAP
    from backend.agent_runtime.tools import get_all_workbench_tools

    tools = {t.name: t for t in get_all_workbench_tools()}
    assert "get_market_sentiment" in tools
    assert "get_crypto_derivatives" in tools
    # 子代理按 authority group 取工具，必须在 a2-research 里
    assert TOOL_GROUP_MAP["get_market_sentiment"] == "a2-research"
    assert TOOL_GROUP_MAP["get_crypto_derivatives"] == "a2-research"
    # 入参 schema 要能表达 market / symbol
    sentiment_fields = set(tools["get_market_sentiment"].args_schema.model_fields)
    assert "market" in sentiment_fields
    deriv_fields = set(tools["get_crypto_derivatives"].args_schema.model_fields)
    assert "symbol" in deriv_fields


def test_native_market_sentiment_passes_market_through(monkeypatch) -> None:
    """wrapper 把 market 参数原样交给 bridge handler（路由逻辑在 handler 里）。"""
    from types import SimpleNamespace

    from backend.agent_runtime import tools as tools_module
    from backend.app_services.execution_policy import ExecutionMode

    seen: dict = {}

    class _StubGuard:
        def require(self, *args, **kwargs):
            return None

    class _StubPolicy:
        def decide(self, name):
            return SimpleNamespace(mode=ExecutionMode.AUTO_SAFE, reason=None, next_action=None)

    class _StubBridge:
        _specs = {
            "get_market_sentiment": SimpleNamespace(
                domain="market-data",
                required_authority=tools_module.AuthorityLevel.A2,
                evidence_refs=[],
            )
        }
        execution_policy = _StubPolicy()
        permission_guard = _StubGuard()

        def __init__(self):
            self._handlers = {"get_market_sentiment": self._handle}

        def _handle(self, arguments):
            seen.update(arguments)
            return {"market": arguments.get("market") or "CN"}

        def _record_execution(self, **kwargs):
            return None

    monkeypatch.setattr(tools_module, "_get_bridge", lambda: _StubBridge())
    tools_module.get_market_sentiment.invoke({"market": "CRYPTO"})
    assert seen.get("market") == "CRYPTO"

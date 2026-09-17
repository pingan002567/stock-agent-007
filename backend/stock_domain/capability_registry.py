"""Mode A capability registry: named data capabilities Agents may invoke.

Credentials never appear here — only schemas, providers, and auth *methods*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityParam:
    name: str
    type: str
    required: bool = False
    description: str = ""
    default: Any = None


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    providers: tuple[str, ...]
    params: tuple[CapabilityParam, ...] = ()
    returns_summary: str = ""
    limitations: str = ""
    rate_limit_hint: str = ""


CAPABILITIES: dict[str, CapabilitySpec] = {
    "quote": CapabilitySpec(
        name="quote",
        description="个股实时/近端报价（最新价、涨跌幅等）",
        providers=("eastmoney", "akshare", "tonghuashun", "tushare", "yfinance", "pytdx", "baostock", "longbridge", "tickflow"),
        params=(CapabilityParam("symbol", "str", True, "股票代码，如 600519 / AAPL"),),
        returns_summary="last, change_pct, updated_at, source, degraded",
        limitations="部分源对港美股覆盖有限；失败时换源而非编造",
        rate_limit_hint="≥1–3s/次（公开爬虫源更严）",
    ),
    "history": CapabilitySpec(
        name="history",
        description="个股日K历史",
        providers=("eastmoney", "akshare", "tonghuashun", "tushare", "yfinance", "pytdx", "baostock", "longbridge"),
        params=(
            CapabilityParam("symbol", "str", True, "股票代码"),
            CapabilityParam("days", "int", False, "回溯交易日数", 30),
        ),
        returns_summary="items[{date,open,high,low,close,volume}], source",
        rate_limit_hint="≥1–3s/次",
    ),
    "financial": CapabilitySpec(
        name="financial",
        description="个股财务报表摘要",
        providers=("eastmoney", "akshare", "tushare", "yfinance"),
        params=(CapabilityParam("symbol", "str", True, "股票代码"),),
        returns_summary="营收/净利/资产负债等科目；字段因源而异",
        rate_limit_hint="低频；可缓存数日",
    ),
    "industry_boards": CapabilitySpec(
        name="industry_boards",
        description="行业/板块列表与涨跌快照",
        providers=("eastmoney", "akshare", "tonghuashun"),
        params=(),
        returns_summary="[{industry, change_pct, rank, …}]",
        limitations="东财不可用时优先 tonghuashun；口径可能不一致",
        rate_limit_hint="≥3s（东财易断连）",
    ),
    "industry_constituents": CapabilitySpec(
        name="industry_constituents",
        description="指定行业成分股（价/涨跌/PE 等）",
        providers=("eastmoney", "akshare", "tonghuashun"),
        params=(CapabilityParam("industry", "str", True, "行业名；东财如酿酒行业，同花顺如白酒"),),
        returns_summary="[{symbol,name,price,change_pct,pe,pb,cap_est}]",
        limitations="同花顺无原生成分接口时回退主表+现货拼装",
        rate_limit_hint="≥3s/行业",
    ),
    "sectors": CapabilitySpec(
        name="sectors",
        description="板块/行业资金与涨跌榜（市场级）",
        providers=("eastmoney", "akshare", "tonghuashun"),
        params=(),
        returns_summary="items[{name,change_pct,net_inflow,leader_stock,…}]",
        limitations="Tushare 不提供此能力",
        rate_limit_hint="≥3s",
    ),
    "market_review": CapabilitySpec(
        name="market_review",
        description="市场综述（指数/涨跌家数等）",
        providers=("eastmoney", "akshare", "tonghuashun"),
        params=(),
        returns_summary="indices / breadth 摘要",
        limitations="Tushare 不提供此能力",
        rate_limit_hint="≥3s",
    ),
    "intel_search": CapabilitySpec(
        name="intel_search",
        description="个股相关情报（新闻/公告摘要）",
        providers=("eastmoney", "akshare"),
        params=(
            CapabilityParam("symbol", "str", True, "股票代码"),
            CapabilityParam("query", "str", False, "可选关键词", ""),
        ),
        returns_summary="items[{title,source,published_at,url}]",
        limitations="Tushare/yfinance 不提供；可辅以 web_search",
        rate_limit_hint="≥3s",
    ),
    "cyq": CapabilitySpec(
        name="cyq",
        description="A 股筹码分布/筹码胜率摘要",
        providers=("eastmoney", "akshare", "tushare"),
        params=(CapabilityParam("symbol", "str", True, "A 股代码"),),
        returns_summary="获利盘/套牢或 cyq_perf 日序列",
        limitations="Tushare cyq_perf 约需 10000 积分；非 A 股无数据",
        rate_limit_hint="Tushare 按积分限流",
    ),
    "moneyflow": CapabilitySpec(
        name="moneyflow",
        description="个股资金流向",
        providers=("eastmoney", "akshare", "tushare"),
        params=(CapabilityParam("symbol", "str", True, "A 股代码"),),
        returns_summary="主力/散户净流入等",
        limitations="Tushare moneyflow≈2000 积分；覆盖以 A 股为主",
        rate_limit_hint="Tushare 按积分限流",
    ),
}


# Provider-facing catalog extras (auth method / rate) — no secrets.
PROVIDER_AGENT_META: dict[str, dict[str, Any]] = {
    "eastmoney": {
        "auth_method": "none_public",
        "auth_description": "公开接口（经 AKShare），无需 API Key",
        "rate_limit_hint": "≥3s/次，易被掐断",
        "default_capabilities": (
            "quote", "history", "financial", "industry_boards",
            "industry_constituents", "sectors", "market_review", "intel_search", "cyq", "moneyflow",
        ),
    },
    "tonghuashun": {
        "auth_method": "none_public",
        "auth_description": "公开接口（经 AKShare 同花顺），无需 API Key",
        "rate_limit_hint": "≥1–3s/次；行业摘要较稳",
        "default_capabilities": (
            "quote", "history", "industry_boards", "industry_constituents", "sectors", "market_review",
        ),
    },
    "akshare": {
        "auth_method": "none_public",
        "auth_description": "多源聚合，无需 API Key",
        "rate_limit_hint": "≥3s/次",
        "default_capabilities": (
            "quote", "history", "financial", "industry_boards",
            "industry_constituents", "sectors", "market_review", "intel_search", "cyq", "moneyflow",
        ),
    },
    "tushare": {
        "auth_method": "token",
        "auth_description": "设置页填写 Token（或环境变量 TUSHARE_TOKEN）；服务端注入，勿要求用户在对话中粘贴",
        "rate_limit_hint": "≈200 次/分钟（免费档）；筹码需高积分",
        "default_capabilities": ("quote", "history", "financial", "cyq", "moneyflow"),
    },
    "yfinance": {
        "auth_method": "none_public",
        "auth_description": "Yahoo Finance，无需 API Key",
        "rate_limit_hint": "≥2s/次",
        "default_capabilities": ("quote", "history", "financial"),
    },
    "pytdx": {
        "auth_method": "none_public",
        "auth_description": "通达信行情服务器，无需 API Key",
        "rate_limit_hint": "本机连接限流",
        "default_capabilities": ("quote", "history"),
    },
    "baostock": {
        "auth_method": "session_login",
        "auth_description": "证券宝 bs.login()，无需 API Key",
        "rate_limit_hint": "低频",
        "default_capabilities": ("quote", "history"),
    },
    "tickflow": {
        "auth_method": "api_key",
        "auth_description": "设置页 API Key（或 TICKFLOW_API_KEY）；服务端注入",
        "rate_limit_hint": "按套餐",
        "default_capabilities": ("quote",),
    },
    "longbridge": {
        "auth_method": "app_key_secret",
        "auth_description": "设置页 App Key/Secret；服务端注入",
        "rate_limit_hint": "按 OpenAPI 配额",
        "default_capabilities": ("quote", "history"),
    },
}


def get_capability(name: str) -> CapabilitySpec | None:
    return CAPABILITIES.get(name)


def list_capability_names() -> list[str]:
    return sorted(CAPABILITIES)


def providers_for_capability(name: str) -> tuple[str, ...]:
    spec = CAPABILITIES.get(name)
    return spec.providers if spec else ()


def capabilities_for_provider(provider_id: str) -> list[str]:
    meta = PROVIDER_AGENT_META.get(provider_id) or {}
    declared = meta.get("default_capabilities")
    if declared:
        return [c for c in declared if c in CAPABILITIES]
    return [c for c, spec in CAPABILITIES.items() if provider_id in spec.providers]


def capability_to_dict(spec: CapabilitySpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "providers": list(spec.providers),
        "params": [
            {
                "name": p.name,
                "type": p.type,
                "required": p.required,
                "description": p.description,
                "default": p.default,
            }
            for p in spec.params
        ],
        "returns_summary": spec.returns_summary,
        "limitations": spec.limitations,
        "rate_limit_hint": spec.rate_limit_hint,
    }

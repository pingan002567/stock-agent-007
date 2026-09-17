# -*- coding: utf-8 -*-
from __future__ import annotations

DEFAULT_DATA_SOURCES = {
    "providers": {
        "CN": {"provider": "eastmoney", "label": "A 股", "description": "东方财富"},
        "HK": {"provider": "eastmoney", "label": "港股", "description": "东方财富"},
        "US": {"provider": "yfinance", "label": "美股", "description": "yfinance (Yahoo Finance)"},
    },
    "provider_credentials": {},
    "provider_states": {},
}

# 设置页可填写的 API 凭证（保存到档案 DB；环境变量同名时优先读 DB 已保存值）
PROVIDER_CREDENTIAL_SCHEMA: dict[str, list[dict[str, str | bool]]] = {
    "tushare": [
        {
            "key": "token",
            "label": "Token",
            "env": "TUSHARE_TOKEN",
            "secret": True,
            "hint": (
                "约 5000 积分可覆盖日线/行情/财务/资金流(moneyflow≈2000)；"
                "每日筹码 cyq_perf 约需 10000 积分。市场综述/板块/情报由其他源承接，不算降级。"
            ),
        },
    ],
    "tickflow": [
        {"key": "api_key", "label": "API Key", "env": "TICKFLOW_API_KEY", "secret": True},
    ],
    "longbridge": [
        {"key": "app_key", "label": "App Key", "env": "LONGBRIDGE_APP_KEY", "secret": True},
        {"key": "app_secret", "label": "App Secret", "env": "LONGBRIDGE_APP_SECRET", "secret": True},
    ],
}

AVAILABLE_PROVIDERS = [
    {
        "id": "eastmoney",
        "name": "东方财富",
        "markets": ["CN", "HK"],
        "free": True,
        "enabled_by_default": True,
        "description": "东方财富公开行情接口（经 AKShare 封装），A 股/港股实时行情、K 线、板块与情报",
        "requirements": "pip install akshare",
    },
    {
        "id": "tonghuashun",
        "name": "同花顺",
        "markets": ["CN", "HK"],
        "free": True,
        "enabled_by_default": True,
        "description": "同花顺公开数据接口（经 AKShare 封装），A 股/港股行情、板块与同花顺特色指标",
        "requirements": "pip install akshare",
    },
    {
        "id": "akshare",
        "name": "AKShare（聚合）",
        "markets": ["CN", "HK"],
        "free": True,
        "enabled_by_default": True,
        "description": "AKShare 多源聚合：东方财富、新浪、腾讯等，覆盖 A 股/港股行情与情报",
        "requirements": "pip install akshare",
    },
    {
        "id": "tickflow",
        "name": "TickFlow",
        "markets": ["CN"],
        "free": False,
        "enabled_by_default": False,
        "description": "A 股 Tick 级实时行情数据，需 TICKFLOW_API_KEY",
        "requirements": "pip install tickflow && set TICKFLOW_API_KEY",
    },
    {
        "id": "tushare",
        "name": "Tushare Pro",
        "markets": ["CN", "HK"],
        "free": False,
        "enabled_by_default": False,
        "description": (
            "Tushare Pro：A/港股行情、K 线、财务、资金流等。"
            "不提供市场综述/板块/情报（自动改走其他源，不算降级）。"
            "建议 ≥5000 积分；每日筹码 cyq_perf 约需 10000。"
        ),
        "requirements": "pip install tushare && Token（建议 ≥5000；筹码 ~10000）",
    },
    {
        "id": "pytdx",
        "name": "Pytdx（通达信）",
        "markets": ["CN"],
        "free": True,
        "enabled_by_default": True,
        "description": "通过 pytdx 直连通达信行情服务器，免费，无需 API Key，仅限 A 股",
        "requirements": "pip install pytdx",
    },
    {
        "id": "baostock",
        "name": "Baostock（证券宝）",
        "markets": ["CN"],
        "free": True,
        "enabled_by_default": True,
        "description": "证券宝免费 A 股数据，需 bs.login()，无需 API Key",
        "requirements": "pip install baostock",
    },
    {
        "id": "yfinance",
        "name": "YFinance",
        "markets": ["US"],
        "free": True,
        "enabled_by_default": True,
        "description": "Yahoo Finance 美股实时行情、历史 K 线、财务数据，免费",
        "requirements": "pip install yfinance",
    },
    {
        "id": "longbridge",
        "name": "Longbridge（长桥证券）",
        "markets": ["CN", "HK", "US"],
        "free": False,
        "enabled_by_default": False,
        "description": "长桥证券 OpenAPI 多市场实时行情，需 LONGBRIDGE_APP_KEY / APP_SECRET",
        "requirements": "pip install longbridge && set LONGBRIDGE_APP_KEY / APP_SECRET",
    },
]

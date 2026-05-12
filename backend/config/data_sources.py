# -*- coding: utf-8 -*-
from __future__ import annotations

DEFAULT_DATA_SOURCES = {
    "providers": {
        "CN": {"provider": "akshare", "label": "A 股", "description": "AKShare（东方财富/新浪）"},
        "HK": {"provider": "akshare", "label": "港股", "description": "AKShare（东方财富/同花顺）"},
        "US": {"provider": "yfinance", "label": "美股", "description": "yfinance (Yahoo Finance)"},
    },
}

AVAILABLE_PROVIDERS = [
    {
        "id": "akshare",
        "name": "AKShare",
        "markets": ["CN", "HK"],
        "description": "基于 AKShare 开源库，覆盖 A 股/港股实时行情、历史 K 线、情报搜索和板块分析",
        "requirements": "pip install akshare",
    },
    {
        "id": "tickflow",
        "name": "TickFlow",
        "markets": ["CN"],
        "description": "A 股 Tick 级实时行情数据，需 TICKFLOW_API_KEY",
        "requirements": "pip install tickflow && set TICKFLOW_API_KEY",
    },
    {
        "id": "tushare",
        "name": "Tushare Pro",
        "markets": ["CN", "HK"],
        "description": "Tushare Pro 金融数据接口，覆盖 A 股/港股行情、历史、财务数据",
        "requirements": "pip install tushare && set TUSHARE_TOKEN",
    },
    {
        "id": "pytdx",
        "name": "Pytdx（通达信）",
        "markets": ["CN"],
        "description": "通过 pytdx 直连通达信行情服务器，免费，无需 API Key，仅限 A 股",
        "requirements": "pip install pytdx",
    },
    {
        "id": "baostock",
        "name": "Baostock（证券宝）",
        "markets": ["CN"],
        "description": "证券宝免费 A 股数据，需 bs.login()，无需 API Key",
        "requirements": "pip install baostock",
    },
    {
        "id": "yfinance",
        "name": "YFinance",
        "markets": ["US"],
        "description": "Yahoo Finance 美股实时行情、历史 K 线、财务数据，免费",
        "requirements": "pip install yfinance",
    },
    {
        "id": "longbridge",
        "name": "Longbridge（长桥证券）",
        "markets": ["CN", "HK", "US"],
        "description": "长桥证券 OpenAPI 多市场实时行情，需 LONGBRIDGE_APP_KEY / APP_SECRET",
        "requirements": "pip install longbridge && set LONGBRIDGE_APP_KEY / APP_SECRET",
    },
    {
        "id": "mock",
        "name": "模拟数据",
        "markets": ["CN", "HK", "US"],
        "description": "本地确定性模拟数据，无需网络连接，适合开发和演示",
        "requirements": "",
    },
]

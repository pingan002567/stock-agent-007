# -*- coding: utf-8 -*-
from __future__ import annotations

DEFAULT_INTEL_SOURCES = {
    "providers": {
        "news_search": {
            "provider": "eastmoney",
            "enabled": True,
            "api_key": None,
            "label": "新闻搜索",
            "description": "东方财富个股新闻（默认，免费，无需 API Key）",
        },
        "social_sentiment": {
            "provider": "none",
            "enabled": False,
            "api_key": None,
            "label": "社交舆情",
            "description": "未启用（可选 Stock Sentiment API / Reddit / X / Polymarket）",
        },
    },
}

AVAILABLE_INTEL_PROVIDERS = [
    {
        "id": "eastmoney",
        "name": "东方财富",
        "category": "news_search",
        "markets": ["CN", "HK"],
        "free": True,
        "api_key_required": False,
        "description": "东方财富个股新闻、股东、财务等情报（经 AKShare）",
        "requirements": "pip install akshare",
    },
    {
        "id": "tonghuashun",
        "name": "同花顺",
        "category": "news_search",
        "markets": ["CN", "HK"],
        "free": True,
        "api_key_required": False,
        "description": "同花顺板块与同花顺特色情报（经 AKShare）",
        "requirements": "pip install akshare",
    },
    {
        "id": "akshare",
        "name": "AKShare（聚合）",
        "category": "news_search",
        "markets": ["CN", "HK"],
        "free": True,
        "api_key_required": False,
        "description": "通过 AKShare 聚合东方财富等多源情报",
        "requirements": "pip install akshare",
    },
    {
        "id": "yfinance",
        "name": "Yahoo Finance",
        "category": "news_search",
        "markets": ["US"],
        "free": True,
        "api_key_required": False,
        "description": "通过 yfinance 获取美股 Yahoo Finance 真实新闻",
        "requirements": "pip install yfinance",
    },
]

AVAILABLE_SENTIMENT_PROVIDERS = [
    {
        "id": "none",
        "name": "未启用",
        "category": "social_sentiment",
        "markets": [],
        "free": True,
        "api_key_required": False,
        "description": "不启用社交舆情搜索",
        "requirements": "",
    },
]

MARKET_NEWS_PROVIDER_MAP: dict[str, list[dict]] = {
    "CN": [
        {"id": "eastmoney", "name": "东方财富", "type": "financial_news"},
        {"id": "tonghuashun", "name": "同花顺", "type": "financial_news"},
    ],
    "HK": [
        {"id": "eastmoney", "name": "东方财富", "type": "financial_news"},
        {"id": "tonghuashun", "name": "同花顺", "type": "financial_news"},
    ],
    "US": [
        {"id": "yfinance", "name": "Yahoo Finance", "type": "financial_news"},
    ],
}

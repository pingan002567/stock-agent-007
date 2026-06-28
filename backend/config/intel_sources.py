# -*- coding: utf-8 -*-
from __future__ import annotations

DEFAULT_INTEL_SOURCES = {
    "providers": {
        "news_search": {
            "provider": "akshare",
            "api_key": None,
            "label": "新闻搜索",
            "description": "AKShare 东方财富个股新闻（默认，无需 API Key）",
        },
        "social_sentiment": {
            "provider": "none",
            "api_key": None,
            "label": "社交舆情",
            "description": "未启用（可选 Stock Sentiment API / Reddit / X / Polymarket）",
        },
    },
}

AVAILABLE_INTEL_PROVIDERS = [
    {
        "id": "akshare",
        "name": "AKShare 东方财富",
        "category": "news_search",
        "markets": ["CN", "HK"],
        "api_key_required": False,
        "description": "通过 AKShare 获取东方财富个股新闻、股东、财务等情报",
        "requirements": "pip install akshare",
    },
    {
        "id": "yfinance",
        "name": "Yahoo Finance",
        "category": "news_search",
        "markets": ["US"],
        "api_key_required": False,
        "description": "通过 yfinance 获取美股 Yahoo Finance 真实新闻",
        "requirements": "pip install yfinance",
    },
    {
        "id": "mock",
        "name": "模拟新闻",
        "category": "news_search",
        "markets": ["CN", "HK", "US"],
        "api_key_required": False,
        "description": "本地模拟新闻数据，无需网络连接",
        "requirements": "",
    },
]

AVAILABLE_SENTIMENT_PROVIDERS = [
    {
        "id": "none",
        "name": "未启用",
        "category": "social_sentiment",
        "markets": [],
        "api_key_required": False,
        "description": "不启用社交舆情搜索",
        "requirements": "",
    },
]

MARKET_NEWS_PROVIDER_MAP: dict[str, list[dict]] = {
    "CN": [
        {"id": "akshare", "name": "AKShare 东方财富", "type": "financial_news"},
    ],
    "HK": [
        {"id": "akshare", "name": "AKShare 港股", "type": "financial_news"},
    ],
    "US": [
        {"id": "yfinance", "name": "Yahoo Finance", "type": "financial_news"},
    ],
}

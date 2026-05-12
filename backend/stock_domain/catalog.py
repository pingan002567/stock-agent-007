from __future__ import annotations

from typing import Any, Dict, List, Optional


STOCKS: Dict[str, Dict[str, object]] = {
    "600519": {
        "symbol": "600519",
        "name": "贵州茅台",
        "market": "CN",
        "industry": "白酒",
        "sector": "消费 / 白酒",
        "aliases": ["maotai", "茅台", "贵州茅台"],
        "price": 1678.40,
        "change_pct": 1.84,
        "score": 72,
        "risk_label": "风险中",
        "stance": "观察仓",
        "confidence": "中",
    },
    "688256": {
        "symbol": "688256",
        "name": "寒武纪",
        "market": "CN",
        "industry": "半导体",
        "sector": "电子 / 半导体",
        "aliases": ["寒武纪", "688256", "cambricon"],
        "price": 65.80,
        "change_pct": 2.35,
        "score": 55,
        "risk_label": "风险高",
        "stance": "观望",
        "confidence": "低",
    },
    "HK00700": {
        "symbol": "HK00700",
        "name": "腾讯控股",
        "market": "HK",
        "industry": "互联网",
        "sector": "港股互联网",
        "aliases": ["00700", "tencent", "腾讯", "腾讯控股"],
        "price": 386.80,
        "change_pct": -2.16,
        "score": 61,
        "risk_label": "风险中高",
        "stance": "降低暴露",
        "confidence": "低",
    },
    "000858": {
        "symbol": "000858",
        "name": "五粮液",
        "market": "CN",
        "industry": "白酒",
        "sector": "消费 / 白酒",
        "aliases": ["五粮液", "000858", "wuliangye"],
        "price": 142.50,
        "change_pct": 0.65,
        "score": 68,
        "risk_label": "风险中",
        "stance": "观察仓",
        "confidence": "中",
    },
    "AAPL": {
        "symbol": "AAPL",
        "name": "Apple",
        "market": "US",
        "industry": "消费电子",
        "sector": "大型科技",
        "aliases": ["apple", "苹果", "aapl"],
        "price": 193.70,
        "change_pct": 0.92,
        "score": 76,
        "risk_label": "集中度高",
        "stance": "减至上限内",
        "confidence": "中",
    },
    "002594": {
        "symbol": "002594",
        "name": "比亚迪",
        "market": "CN",
        "industry": "新能源汽车",
        "sector": "汽车 / 新能源",
        "aliases": ["比亚迪", "byd", "002594"],
        "price": 285.50,
        "change_pct": 1.25,
        "score": 70,
        "risk_label": "风险中",
        "stance": "观察仓",
        "confidence": "中",
    },
    "HK01211": {
        "symbol": "HK01211",
        "name": "比亚迪股份",
        "market": "HK",
        "industry": "新能源汽车",
        "sector": "港股汽车",
        "aliases": ["01211", "比亚迪股份", "byd company"],
        "price": 268.00,
        "change_pct": 0.85,
        "score": 68,
        "risk_label": "风险中",
        "stance": "观察仓",
        "confidence": "中",
    },
}

_repo: Any = None


def set_repo(repo: Any) -> None:
    global _repo
    _repo = repo


def normalize_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if raw in {"00700", "700"}:
        return "HK00700"
    if raw in STOCKS:
        return raw
    # Auto-prefix 5-digit codes as HK (CN codes are 6 digits)
    if raw.isdigit() and len(raw) == 5 and not raw.startswith("HK"):
        candidates = search_stocks(raw)
        if candidates:
            return str(candidates[0]["symbol"])
        return f"HK{raw}"
    # 6-digit numeric code → CN A-share (e.g. 000858 sz, 600519 sh, 688256 star)
    if raw.isdigit() and len(raw) == 6:
        candidates = search_stocks(raw)
        if candidates:
            return str(candidates[0]["symbol"])
        return raw  # Unknown CN stock, return as-is for provider attempt
    # Resolve Chinese name / alias to stock code
    results = search_stocks(symbol)
    if results:
        return str(results[0]["symbol"])
    return raw


def _overlay_stock_dict(master: Any, stock_dict: Dict[str, object] | None = None) -> Dict[str, object]:
    result: Dict[str, object] = {
        "symbol": master.symbol,
        "name": master.name,
        "market": master.market,
        "industry": master.industry or "",
        "sector": master.sector or "",
        "aliases": master.aliases,
        "price": 0.0,
        "change_pct": 0.0,
        "score": 0,
        "risk_label": "",
        "stance": "",
        "confidence": "",
    }
    if stock_dict is not None:
        for key in ("price", "change_pct", "score", "risk_label", "stance", "confidence"):
            if key in stock_dict:
                result[key] = stock_dict[key]
    elif _repo is not None:
        quote = _repo.get_stock_quote(master.symbol)
        if quote is not None:
            result["price"] = quote.last
            result["change_pct"] = quote.change_pct
    return result


def get_stock(symbol: str) -> Optional[Dict[str, object]]:
    normalized = normalize_symbol(symbol)
    stock_dict = STOCKS.get(normalized)
    if _repo is not None:
        master = _repo.get_stock_master(normalized)
        if master is not None:
            return _overlay_stock_dict(master, stock_dict)
    if stock_dict is not None:
        return stock_dict
    # Fallback: search by name/alias (handles Chinese names, partial codes)
    results = search_stocks(symbol)
    if results:
        stock = results[0]
        resolved_symbol = str(stock["symbol"])
        stock_dict = STOCKS.get(resolved_symbol)
        if stock_dict is not None:
            return stock_dict
        return stock
    # P3: For valid numeric formats, return a synthetic entry so providers
    # can attempt data lookup even without a catalog entry.
    # This unblocks unknown A-share / HK stocks at the cost of mock quality.
    if normalized.isdigit():
        if len(normalized) == 6:
            return {
                "symbol": normalized, "name": normalized, "market": "CN",
                "industry": "", "sector": "", "aliases": [],
                "price": 0.0, "change_pct": 0.0,
                "score": 0, "risk_label": "", "stance": "", "confidence": "",
            }
        if len(normalized) == 5 and not normalized.startswith("HK"):
            return {
                "symbol": f"HK{normalized}", "name": normalized, "market": "HK",
                "industry": "", "sector": "", "aliases": [],
                "price": 0.0, "change_pct": 0.0,
                "score": 0, "risk_label": "", "stance": "", "confidence": "",
            }
    return None


def search_stocks(query: str) -> List[Dict[str, object]]:
    q = query.strip().lower()
    if _repo is not None:
        masters = _repo.search_stock_master(q)
        if masters:
            return [_overlay_stock_dict(m, STOCKS.get(m.symbol)) for m in masters]
    if not q:
        return list(STOCKS.values())
    results = []
    for item in STOCKS.values():
        haystack = " ".join(
            [str(item["symbol"]), str(item["name"]), str(item["market"])]
            + [str(alias) for alias in item.get("aliases", [])]
        ).lower()
        if q in haystack or haystack in q:
            results.append(item)
    return results

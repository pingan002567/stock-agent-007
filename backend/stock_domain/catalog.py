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
    try:
        from backend.stock_domain.catalog_tools import KNOWN_STOCK_ALIASES
        alias_seed = KNOWN_STOCK_ALIASES.get(str(master.symbol), [])
    except Exception:
        alias_seed = []
    aliases = list(dict.fromkeys([*(master.aliases or []), *alias_seed]))
    instrument_type = str(getattr(master, "instrument_type", None) or "").strip().lower()
    if instrument_type not in {"stock", "etf", "fund", "other"}:
        instrument_type = infer_instrument_type(
            str(master.symbol),
            name=str(master.name or ""),
            industry=str(master.industry or ""),
            sector=str(master.sector or ""),
            aliases=aliases,
        )
    result: Dict[str, object] = {
        "symbol": master.symbol,
        "name": master.name,
        "market": master.market,
        "industry": master.industry or "",
        "sector": master.sector or "",
        "aliases": aliases,
        "instrument_type": instrument_type,
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
        if stock_dict.get("instrument_type") and not getattr(master, "instrument_type", None):
            result["instrument_type"] = stock_dict["instrument_type"]
    elif _repo is not None:
        quote = _repo.get_stock_quote(master.symbol)
        if quote is not None:
            result["price"] = quote.last
            result["change_pct"] = quote.change_pct
    return result


# 常见 A 股宽基 / 行业 ETF 前缀或整码（启发式，可被 master.instrument_type 覆盖）
_CN_ETF_PREFIXES = ("51", "15", "56", "58", "159")
_KNOWN_ETF_SYMBOLS = {
    "510300", "510500", "512880", "512800", "510050", "159915", "159919",
    "SPY", "QQQ", "DIA", "IWM", "ARKK", "02800", "02801",
}


def infer_instrument_type(
    symbol: str,
    *,
    name: str = "",
    industry: str = "",
    sector: str = "",
    aliases: list | None = None,
) -> str:
    sym = str(symbol or "").strip().upper()
    hay = " ".join(
        [sym, name, industry, sector, *(aliases or [])]
    ).upper()
    if "ETF" in hay or "交易型开放式" in hay or "指数基金" in (name or ""):
        return "etf"
    if sym in _KNOWN_ETF_SYMBOLS:
        return "etf"
    # A 股 6 位：51xxxx / 15xxxx 等 ETF 常见段
    if len(sym) == 6 and sym.isdigit() and sym.startswith(_CN_ETF_PREFIXES):
        return "etf"
    if "FUND" in hay or "基金" in (name or industry or sector):
        # 宽基 ETF 已在上面；其余基金归 fund
        if "ETF" not in hay:
            return "fund"
    return "stock"


def is_etf_like(symbol: str, stock: Dict[str, object] | None = None) -> bool:
    info = stock if stock is not None else (get_stock(symbol) or {})
    itype = str(info.get("instrument_type") or "").lower()
    if itype in {"etf", "fund"}:
        return True
    return infer_instrument_type(
        str(info.get("symbol") or symbol),
        name=str(info.get("name") or ""),
        industry=str(info.get("industry") or ""),
        sector=str(info.get("sector") or ""),
        aliases=list(info.get("aliases") or []),  # type: ignore[arg-type]
    ) in {"etf", "fund"}



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
                "instrument_type": infer_instrument_type(normalized),
                "price": 0.0, "change_pct": 0.0,
                "score": 0, "risk_label": "", "stance": "", "confidence": "",
            }
        if len(normalized) == 5 and not normalized.startswith("HK"):
            return {
                "symbol": f"HK{normalized}", "name": normalized, "market": "HK",
                "industry": "", "sector": "", "aliases": [],
                "instrument_type": "stock",
                "price": 0.0, "change_pct": 0.0,
                "score": 0, "risk_label": "", "stance": "", "confidence": "",
            }
    return None


def search_stocks(query: str) -> List[Dict[str, object]]:
    q = query.strip().lower()
    if _repo is not None:
        masters = _repo.search_stock_master(q)
        if not masters and q:
            try:
                from backend.stock_domain.catalog_tools import KNOWN_STOCK_ALIASES

                for symbol, aliases in KNOWN_STOCK_ALIASES.items():
                    if any(q in alias.lower() for alias in aliases):
                        master = _repo.get_stock_master(symbol)
                        if master is not None:
                            masters = [master]
                            break
            except Exception:
                pass
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

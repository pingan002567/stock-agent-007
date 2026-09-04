from __future__ import annotations

from typing import Any

from backend.schemas import StockMaster
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.providers import AkShareMarketDataProvider

# 知名别名补全（profile 英文/网站无法覆盖的中文俗称）
KNOWN_STOCK_ALIASES: dict[str, list[str]] = {
    "688825": ["长鑫存储", "cxmt", "CXMT", "ChangXin"],
    "600519": ["茅台", "贵州茅台", "maotai"],
    "000858": ["五粮液", "wuliangye"],
    "AAPL": ["苹果", "Apple"],
    "HK00700": ["腾讯", "Tencent", "00700"],
}


def enrich_stock_master(symbol: str, *, force: bool = False) -> dict:
    """用巨潮 profile + 已知别名回填 industry/sector/aliases。"""
    repo = provider_router.repo
    if repo is None:
        return {"ok": False, "error": "repository not initialized"}

    normalized = symbol.strip().upper()
    master = repo.get_stock_master(normalized)
    if master is None:
        return {"ok": False, "error": f"unknown symbol: {normalized}"}

    needs_enrichment = force or not master.industry or not master.aliases
    if not needs_enrichment:
        return {"ok": True, "skipped": True, "symbol": normalized}

    meta: dict = {}
    primary = provider_router.primary
    if isinstance(primary, AkShareMarketDataProvider) and master.market == "CN":
        meta = primary.fetch_profile_metadata(normalized)

    aliases = list(dict.fromkeys(
        [*master.aliases, *KNOWN_STOCK_ALIASES.get(normalized, []), *meta.get("aliases", [])]
    ))
    industry = meta.get("industry") or master.industry
    sector = meta.get("sector") or master.sector or industry

    updated = StockMaster(
        symbol=normalized,
        name=meta.get("company_name") or master.name,
        market=master.market,
        industry=industry,
        sector=sector,
        aliases=aliases,
        is_active=master.is_active,
        created_at=master.created_at,
        updated_at=master.updated_at,
    )
    repo.upsert_stock_master(updated)
    return {
        "ok": True,
        "symbol": normalized,
        "industry": industry,
        "sector": sector,
        "aliases": aliases,
    }


def import_a_share_master() -> dict:
    """Import all A-share stocks from AKShare into stock_master table.

    Returns import summary with total/imported/failed counts.
    """
    repo = provider_router.repo
    if repo is None:
        return {"ok": False, "error": "repository not initialized"}

    primary = provider_router.primary
    if not isinstance(primary, AkShareMarketDataProvider):
        return {"ok": False, "error": "primary provider is not AkShare"}

    items = primary.import_a_share_master()
    if not items:
        return {"ok": False, "error": "no A-share stocks returned from AKShare"}

    master_items = [
        StockMaster(
            symbol=item["symbol"],
            name=item["name"],
            market=item["market"],
            industry="",
            sector="",
            aliases=[],
        )
        for item in items
    ]

    count = repo.batch_upsert_stock_master(master_items)
    return {"ok": True, "total": len(master_items), "imported": count}


def import_us_stock_master() -> dict:
    """Import US stocks from AKShare (fallback to built-in list) into stock_master table."""
    repo = provider_router.repo
    if repo is None:
        return {"ok": False, "error": "repository not initialized"}
    primary = provider_router.primary
    if not isinstance(primary, AkShareMarketDataProvider):
        return {"ok": False, "error": "primary provider is not AkShare"}
    items = primary.import_us_stock_master()
    if not items:
        return {"ok": False, "error": "no US stocks returned from provider"}
    master_items = [
        StockMaster(symbol=item["symbol"], name=item["name"], market=item["market"], industry="", sector="", aliases=[])
        for item in items
    ]
    count = repo.batch_upsert_stock_master(master_items)
    return {"ok": True, "total": len(master_items), "imported": count}


def import_hk_stock_master() -> dict:
    """Import all HK stocks from AKShare into stock_master table.

    Returns import summary with total/imported/failed counts.
    """
    repo = provider_router.repo
    if repo is None:
        return {"ok": False, "error": "repository not initialized"}

    primary = provider_router.primary
    if not isinstance(primary, AkShareMarketDataProvider):
        return {"ok": False, "error": "primary provider is not AkShare"}

    items = primary.import_hk_stock_master()
    if not items:
        return {"ok": False, "error": "no HK stocks returned from AKShare"}

    master_items = [
        StockMaster(
            symbol=item["symbol"],
            name=item["name"],
            market=item["market"],
            industry="",
            sector="",
            aliases=[],
        )
        for item in items
    ]

    count = repo.batch_upsert_stock_master(master_items)
    return {"ok": True, "total": len(master_items), "imported": count}

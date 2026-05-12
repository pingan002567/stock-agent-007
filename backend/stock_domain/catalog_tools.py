from __future__ import annotations

from typing import Any

from backend.schemas import StockMaster
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.providers import AkShareMarketDataProvider


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

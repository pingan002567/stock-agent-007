from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import WatchlistItem, model_to_dict
from backend.stock_domain.catalog import get_stock

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist(request: Request, services: AppServices = Depends(get_services)):
    """Mode B list: enrich from provider_router cache/SQLite; never blank on degrade."""
    from backend.stock_domain.provider_router import provider_router

    items = services.repo.list_watchlist()
    result = []
    degraded_count = 0
    for item in items:
        d = model_to_dict(item)
        stock = get_stock(item.symbol)
        d["market"] = str(stock["market"]) if stock else ""
        price_block: dict = {
            "last": None,
            "change_pct": None,
            "updated_at": None,
            "degraded": True,
            "degraded_reason": "quote unavailable",
            "stale": True,
            "channel": "mode_b",
        }
        try:
            quote = provider_router.get_quote(item.symbol)
            coverage = quote.coverage if isinstance(quote.coverage, dict) else {}
            price_block = {
                "last": quote.last if not quote.degraded or quote.last else None,
                "change_pct": quote.change_pct,
                "updated_at": quote.updated_at,
                "degraded": bool(quote.degraded),
                "degraded_reason": quote.degraded_reason,
                "stale": bool(coverage.get("stale")),
                "from_cache": bool(coverage.get("from_cache")),
                "source": quote.source,
                "channel": "mode_b",
            }
            if quote.degraded or price_block["last"] is None:
                degraded_count += 1
        except Exception as exc:
            price_block["degraded_reason"] = str(exc)[:160]
            degraded_count += 1
        d["price"] = price_block
        d["quote_degraded"] = bool(price_block.get("degraded") or price_block.get("last") is None)
        result.append(d)
    # Keep list response for SPA compatibility; meta rides on each item + summary hint
    # via first-item sentinel when empty is fine — frontend aggregates quote_degraded.
    if result:
        result[0]["_mode_b"] = {
            "quotes_degraded_count": degraded_count,
            "quotes_total": len(result),
            "note": "行情来自系统缓存通道（Mode B）；降级时展示缓存/占位，不假装实时。",
        }
    return result


@router.post("/items")
def add_watchlist_item(item: WatchlistItem, request: Request, services: AppServices = Depends(get_services)):
    saved = services.repo.upsert_watchlist_item(item)
    services.audit_service.record("watchlist upsert", saved.symbol)
    return model_to_dict(saved)


@router.post("/reorder")
def reorder_watchlist(payload: dict, request: Request, services: AppServices = Depends(get_services)):
    items = payload.get("items", [])
    for entry in items:
        services.repo.update_watchlist_position(entry["symbol"], entry.get("position", 0))
    services.audit_service.record("watchlist reorder", f"{len(items)} items")
    return {"ok": True}


@router.post("/reorder-groups")
def reorder_groups(payload: dict, request: Request, services: AppServices = Depends(get_services)):
    items = payload.get("items", [])
    for entry in items:
        services.repo.update_group_sort(entry["name"], entry.get("sort_order", 0))
    return {"ok": True}


@router.get("/groups")
def list_groups(request: Request, services: AppServices = Depends(get_services)):
    groups = services.repo.list_watchlist_groups()
    seen = {g["name"] for g in groups}
    # Include groups from existing watchlist items not yet in the groups table
    for item in services.repo.list_watchlist():
        gname = item.group or "默认"
        if gname not in seen:
            groups.append({"name": gname, "color": "#6366f1", "sort_order": len(groups)})
            seen.add(gname)
    return groups


@router.post("/groups")
def create_group(payload: dict, request: Request, services: AppServices = Depends(get_services)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name required")
    color = payload.get("color", "#6366f1")
    services.repo.upsert_watchlist_group(name, color)
    services.audit_service.record("watchlist group created", name)
    return {"name": name, "color": color}


@router.put("/groups/{name}")
def update_group(name: str, payload: dict, request: Request, services: AppServices = Depends(get_services)):
    color = payload.get("color", "#6366f1")
    new_name = payload.get("name", name).strip()
    if new_name != name:
        services.repo.rename_watchlist_group(name, new_name)
    services.repo.upsert_watchlist_group(new_name, color)
    services.audit_service.record("watchlist group updated", new_name)
    return {"name": new_name, "color": color}


@router.delete("/groups/{name}")
def delete_group(name: str, request: Request, services: AppServices = Depends(get_services)):
    services.repo.delete_watchlist_group(name)
    services.audit_service.record("watchlist group deleted", name)
    return {"deleted": True}


@router.get("/quotes")
def watchlist_quotes(request: Request, services: AppServices = Depends(get_services)):
    """Mode B quotes for watchlist — prefer cache; surface degraded explicitly."""
    from backend.stock_domain.provider_router import provider_router

    items = services.repo.list_watchlist()
    result = []
    degraded_count = 0
    for item in items:
        stock = get_stock(item.symbol)
        mkt = str(stock["market"]) if stock else ""
        row = {
            "symbol": item.symbol,
            "name": item.name,
            "group": item.group or "默认",
            "monitored": bool(item.monitored),
            "market": mkt,
            "price": None,
            "change_pct": None,
            "degraded": True,
            "degraded_reason": "quote unavailable",
            "channel": "mode_b",
        }
        try:
            quote = provider_router.get_quote(item.symbol)
            row["price"] = quote.last if quote.last else None
            row["change_pct"] = quote.change_pct
            row["degraded"] = bool(quote.degraded) or row["price"] is None
            row["degraded_reason"] = quote.degraded_reason
            row["updated_at"] = quote.updated_at
            row["source"] = quote.source
            if row["degraded"]:
                degraded_count += 1
        except Exception as exc:
            row["degraded_reason"] = str(exc)[:160]
            degraded_count += 1
        result.append(row)
    return {
        "items": result,
        "quotes_degraded_count": degraded_count,
        "quotes_total": len(result),
        "channel": "mode_b",
    }


@router.post("/{symbol}/monitor")
def toggle_monitor(symbol: str, request: Request, services: AppServices = Depends(get_services)):
    items = services.repo.list_watchlist()
    existing = next((i for i in items if i.symbol.upper() == symbol.upper()), None)
    if not existing:
        raise HTTPException(status_code=404, detail="watchlist item not found")
    existing.monitored = not existing.monitored
    saved = services.repo.upsert_watchlist_item(existing)
    services.audit_service.record("watchlist monitor toggle", f"{symbol} monitored={saved.monitored}")
    return model_to_dict(saved)


@router.post("/batch-research")
def batch_research(request: Request, services: AppServices = Depends(get_services)):
    from backend.schemas import ReportGenerateRequest
    items = services.repo.list_watchlist()
    created = []
    for item in items:
        try:
            context = services.context_builder.build_stock_context(item.symbol)
            task = services.task_service.create(f"{context.symbol} 深研", "stock-researcher", "read_quote_and_intel")
            report = services.report_service.generate(
                ReportGenerateRequest(
                    report_type="stock_research", source_type="stock",
                    source_id=context.symbol, title=f"{context.symbol} 深研报告",
                )
            )
            services.audit_service.record("watchlist batch research", f"{item.symbol} task={task.task_id}")
            created.append({"symbol": item.symbol, "task_id": task.task_id, "report_id": report.report_id})
        except Exception:
            created.append({"symbol": item.symbol, "task_id": None, "error": "创建失败"})
    return {"items": created}


@router.delete("/items/{symbol}")
def delete_watchlist_item(symbol: str, request: Request, services: AppServices = Depends(get_services)):
    deleted = services.repo.delete_watchlist_item(symbol)
    services.audit_service.record("watchlist delete", f"{symbol} deleted={deleted}")
    return {"deleted": deleted}

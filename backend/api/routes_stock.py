from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import ReportGenerateRequest, model_to_dict
from backend.stock_domain.catalog import search_stocks
from backend.stock_domain.catalog_tools import import_a_share_master, import_hk_stock_master, import_us_stock_master
from backend.schemas import StockQuote, now_iso
from backend.stock_domain.financial_tools import get_stock_financial
from backend.stock_domain.history_tools import get_daily_history
from backend.stock_domain.intel_tools import search_stock_intel, social_sentiment
from backend.stock_domain.report_tools import generate_stock_dashboard

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search(q: str = ""):
    return {"items": search_stocks(q)}


@router.get("/{symbol}/context")
def stock_context(symbol: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        return model_to_dict(services.context_builder.build_stock_context(symbol))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{symbol}/history")
def stock_history(symbol: str, days: int = 30):
    return get_daily_history(symbol, days)


@router.get("/{symbol}/daily")
def stock_daily_persisted(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 90,
    services: AppServices = Depends(get_services),
):
    items = services.repo.list_stock_daily(symbol.upper(), start_date=start_date, end_date=end_date, limit=limit)
    return {"symbol": symbol.upper(), "total": len(items), "items": [model_to_dict(i) for i in items]}


@router.post("/import-a-share-master")
def import_a_share():
    return import_a_share_master()


@router.post("/import-hk-master")
def import_hk_share():
    return import_hk_stock_master()


@router.post("/import-us-master")
def import_us_share():
    return import_us_stock_master()


@router.get("/{symbol}/intel")
def stock_intel(symbol: str, q: str = ""):
    return search_stock_intel(symbol, q)


@router.get("/{symbol}/sentiment")
def stock_sentiment(symbol: str):
    return social_sentiment(symbol)


@router.get("/{symbol}/dashboard")
def stock_dashboard(symbol: str, request: Request, services: AppServices = Depends(get_services)):
    try:
        context = services.context_builder.build_stock_context(symbol)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return generate_stock_dashboard(context)


@router.get("/{symbol}/financial")
def stock_financial(symbol: str):
    return get_stock_financial(symbol)


@router.post("/{symbol}/research")
def create_research(symbol: str, request: Request, services: AppServices = Depends(get_services)):
    context = services.context_builder.build_stock_context(symbol)
    normalized_symbol = context.symbol
    
    # 检查是否有相同 symbol 的进行中任务
    existing_tasks = services.repo.list_tasks()
    running_tasks = [t for t in existing_tasks if t.title and normalized_symbol in t.title and t.status == "running"]
    if running_tasks:
        return {
            "status": "exists",
            "task": model_to_dict(running_tasks[0]),
            "message": f"{normalized_symbol} 深研任务正在进行中，请稍后查看"
        }
    
    # 检查是否有 24 小时内的已完成任务
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    recent_tasks = [
        t for t in existing_tasks 
        if t.title and normalized_symbol in t.title 
        and t.status == "completed"
        and t.created_at 
        and (now - datetime.fromisoformat(t.created_at.replace('Z', '+00:00'))) < timedelta(hours=24)
    ]
    if recent_tasks:
        return {
            "status": "recent",
            "task": model_to_dict(recent_tasks[0]),
            "message": f"{normalized_symbol} 深研报告已于近期生成"
        }
    
    # 创建新任务
    task = services.task_service.create(f"{context.symbol} 深研", "stock-researcher", "read_quote_and_intel")
    report = services.report_service.generate(
        ReportGenerateRequest(
            report_type="stock_research",
            source_type="stock",
            source_id=context.symbol,
            title=f"{context.symbol} 深研报告",
        )
    )
    services.audit_service.record("stock research created", f"{context.symbol} task={task.task_id} report={report.report_id}")
    return {
        "status": "created",
        "task": model_to_dict(task),
        "report": model_to_dict(report),
        "message": f"{context.symbol} 深研任务已创建，预计 2-3 分钟完成"
    }


@router.post("/collect-quotes")
def collect_quotes(services: AppServices = Depends(get_services)):
    """Trigger an on-demand data collection cycle for monitored watchlist stocks."""
    summary = services.data_collector._collect_once()
    return {"ok": True, "summary": summary}


@router.post("/collect-all-quotes")
def collect_all_quotes(services: AppServices = Depends(get_services)):
    """Collect quotes for ALL stocks in stock_master (batch refresh)."""
    from backend.stock_domain.provider_router import provider_router as _pr

    masters = services.repo.list_stock_master()
    checked = 0
    quotes = 0
    errors: list[dict[str, str]] = []

    for m in masters:
        checked += 1
        try:
            q = _pr.get_quote(m.symbol)
            if not q.degraded:
                services.repo.upsert_stock_quote(StockQuote(
                    symbol=m.symbol,
                    last=q.last,
                    change_pct=q.change_pct,
                    volume=getattr(q, "volume", 0.0),
                    amount=getattr(q, "amount", 0.0),
                    source=q.source,
                    provider=q.source,
                    updated_at=q.updated_at or now_iso(),
                ))
                quotes += 1
        except Exception as exc:
            errors.append({"symbol": m.symbol, "error": str(exc)})
    return {
        "ok": True,
        "total_stocks": len(masters),
        "quotes_fetched": quotes,
        "errors": errors[:20],
    }

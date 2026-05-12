from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from backend.schemas import model_to_dict, now_iso

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.post("/reconnect")
def runtime_reconnect(services: AppServices = Depends(get_services)):
    """Re-initialize AI runtime from persisted config (no restart needed)."""
    status = services.copilot_service.reconnect_runtime()
    return {"ok": True, "agent_runtime": status}


@router.post("/test-connection")
def runtime_test_connection(
    payload: dict,
    services: AppServices = Depends(get_services),
):
    """Test AI model connectivity with given or current config."""
    result = services.copilot_service.test_connection(payload)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/metrics")
def runtime_metrics(request: Request, services: AppServices = Depends(get_services)):
    snapshot = services.runtime_observer.snapshot_metrics()
    return model_to_dict(snapshot)


@router.get("/provider-events")
def provider_events(
    limit: int = 100,
    capability: str | None = None,
    services: AppServices = Depends(get_services),
):
    items = services.runtime_observer.list_provider_events(
        limit=limit, capability=capability
    )
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/copilot-runs")
def copilot_runs(
    limit: int = 100,
    status: str | None = None,
    services: AppServices = Depends(get_services),
):
    items = services.runtime_observer.list_copilot_runs(limit=limit, status=status)
    return {"items": [model_to_dict(item) for item in items]}


@router.get("/copilot-runs/{run_id}")
def copilot_run_detail(run_id: str, services: AppServices = Depends(get_services)):
    item = services.runtime_observer.get_copilot_run_log(run_id)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"copilot run {run_id} not found")
    return model_to_dict(item)


@router.get("/cost-summary")
def cost_summary(services: AppServices = Depends(get_services)):
    """Per-day per-model token usage & cost breakdown."""
    return services.runtime_observer.daily_cost_summary()


@router.get("/data-freshness")
def data_freshness(services: AppServices = Depends(get_services)):
    """Intraday quote staleness check — flags symbols not refreshed in 5+ min during trading hours."""
    from backend.stock_domain.provider_router import provider_router
    from backend.stock_domain.trading_calendar import is_trading_day
    from datetime import datetime, timezone, time

    now = datetime.now(timezone.utc)
    today = now.date()
    market_hours = {
        "CN": (time(9, 30), time(15, 0)),
        "US": (time(9, 30), time(16, 0)),
        "HK": (time(9, 30), time(16, 0)),
    }
    stale: list[dict] = []
    if provider_router.repo is not None:
        try:
            quotes = provider_router.repo.list_stock_quotes()
            for quote in quotes:
                sym = quote.symbol
                market = provider_router._market_of(sym) or "CN"
                if not is_trading_day(market, today):
                    continue
                open_t, close_t = market_hours.get(market, (time(9, 30), time(15, 0)))
                now_local = now.astimezone().time()
                if not (open_t <= now_local <= close_t):
                    continue
                if quote.updated_at is None:
                    stale.append({"symbol": sym, "market": market, "reason": "no_data"})
                    continue
                updated = datetime.fromisoformat(quote.updated_at)
                age_seconds = (now - updated).total_seconds()
                if age_seconds > 300:
                    stale.append(
                        {
                            "symbol": sym,
                            "market": market,
                            "age_seconds": int(age_seconds),
                            "last_updated": quote.updated_at,
                            "reason": "stale",
                        }
                    )
        except Exception:
            import logging

            logging.getLogger("routes_runtime").exception("data_freshness check failed")
    return {
        "stale_count": len(stale),
        "stale_items": stale[:50],
        "checked_at": now_iso(),
    }


@router.get("/cache-stats")
def cache_stats():
    """Process-level memory cache hit/miss statistics per capability."""
    from backend.stock_domain.provider_router import provider_router

    stats = provider_router._mem_cache.stats()
    return {
        "hits": stats["hits"],
        "misses": stats["misses"],
        "hit_rate": stats["hit_rate"],
        "size": stats["size"],
        "maxsize": stats["maxsize"],
    }


@router.get("/regression-cases")
def regression_cases():
    cases = [
        {
            "case_id": "monitor_explain",
            "message": "解释最近一条盯盘事件",
            "page": "monitor",
            "expected_tools": ["get_monitor_events"],
            "mode": "structural",
        },
        {
            "case_id": "paper_review",
            "message": "复盘 paper 调仓效果",
            "page": "holdings",
            "expected_tools": ["analyze_paper_performance"],
            "mode": "structural",
        },
        {
            "case_id": "stock_context",
            "message": "分析 AAPL 当前情况",
            "page": "research",
            "symbol": "AAPL",
            "mode": "structural",
        },
        {
            "case_id": "risk_review",
            "message": "检查投资组合风险",
            "page": "holdings",
            "mode": "structural",
        },
        {
            "case_id": "report_write",
            "message": "生成一份市场复盘报告",
            "page": "overview",
            "mode": "structural",
        },
        {
            "case_id": "strategy_backtest",
            "message": "运行策略回测",
            "page": "strategies",
            "mode": "structural",
        },
        {
            "case_id": "draft_plan",
            "message": "规划调仓方案",
            "page": "holdings",
            "mode": "structural",
        },
        {
            "case_id": "decision_review",
            "message": "复盘最近一次 AI 调仓建议",
            "page": "holdings",
            "mode": "structural",
        },
        {
            "case_id": "risk_scan",
            "message": "分析 AAPL 风险",
            "page": "holdings",
            "symbol": "AAPL",
            "mode": "full",
            "requires_deerflow": True,
        },
    ]
    return {"items": cases}

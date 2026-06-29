from __future__ import annotations

from pathlib import Path
import logging
import threading
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI is required. Install project dependencies from pyproject.toml."
    ) from exc

from backend.api import (
    routes_audit,
    routes_channels,
    routes_copilot,
    routes_decision_journal,
    routes_holdings,
    routes_market,
    routes_monitor,
    routes_overview,
    routes_paper_orders,
    routes_paper_portfolio,
    routes_portfolio,
    routes_pre_trade_reviews,
    routes_rebalance_drafts,
    routes_risk_policies,
    routes_reports,
    routes_review_inbox,
    routes_runtime,
    routes_settings,
    routes_stock,
    routes_strategy,
    routes_tasks,
    routes_watchlist,
    routes_worldcup,
)
from backend.bootstrap import create_services
from backend.stock_domain.provider_router import provider_router


def _warmup_cache() -> None:
    """Preload slow external APIs (AKShare) in background so first user request is fast."""
    import logging

    logger = logging.getLogger("warmup")
    logger.info("warming up data provider cache…")
    try:
        provider_router.get_market_review()
        logger.info("market review cached")
    except Exception as exc:
        logger.warning("market review warmup failed: %s", exc)
    try:
        provider_router.get_sectors()
        logger.info("sectors cached")
    except Exception as exc:
        logger.warning("sectors warmup failed: %s", exc)


def create_app(
    db_path: str = "data/workbench.sqlite3", files_root: str = "data/files"
) -> FastAPI:
    services = create_services(db_path=db_path, files_root=files_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await services.monitor_service.startup()
        await services.data_collector.startup()
        try:
            await services.channel_service.start()
        except Exception:
            logging.getLogger("app").exception("channel service failed to start")
        # Fire-and-forget warmup — data will be cached before most users navigate to overview/market
        threading.Thread(target=_warmup_cache, daemon=True).start()
        try:
            yield
        finally:
            await services.monitor_service.shutdown()
            await services.data_collector.shutdown()
            try:
                await services.channel_service.stop()
            except Exception:
                logging.getLogger("app").exception("channel service failed to stop")

    app = FastAPI(title="AI Stock Workbench", version="0.1.0", lifespan=lifespan)
    app.state.services = services

    @app.get("/api/health", tags=["health"])
    def health():
        agent_runtime = app.state.services.copilot_service.deerflow.status().to_dict()
        return {
            "status": "ok",
            "mode": "single-user-local",
            "runtime": f"deerflow-adapter-{agent_runtime['active_client']}",
            "agent_runtime": agent_runtime,
            "stock_domain": "provider-router",
            "data_provider": provider_router.status().to_dict(),
        }

    @app.get("/app", include_in_schema=False)
    def app_shell():
        return FileResponse(Path("frontend/dist/index.html"))

    for router in [
        routes_audit.router,
        routes_overview.router,
        routes_watchlist.router,
        routes_holdings.router,
        routes_stock.router,
        routes_market.router,
        routes_monitor.router,
        routes_strategy.router,
        routes_rebalance_drafts.router,
        routes_pre_trade_reviews.router,
        routes_paper_orders.router,
        routes_paper_portfolio.router,
        routes_portfolio.router,
        routes_decision_journal.router,
        routes_review_inbox.router,
        routes_risk_policies.router,
        routes_tasks.router,
        routes_reports.router,
        routes_reports.templates_router,
        routes_runtime.router,
        routes_settings.router,
        routes_copilot.router,
        routes_channels.router,
        routes_worldcup.router,
    ]:
        app.include_router(router)

    dist_path = Path("frontend/dist")
    if dist_path.is_dir():
        app.mount(
            "/", StaticFiles(directory=str(dist_path), html=True), name="frontend"
        )

    return app


app = create_app()

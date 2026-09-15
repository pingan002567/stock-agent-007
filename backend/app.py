from __future__ import annotations

from pathlib import Path
import logging
import threading
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI is required. Install project dependencies from pyproject.toml."
    ) from exc

from backend.access_auth import AccessAuthMiddleware, cors_origin_list
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
    routes_scheduled_tasks,
    routes_settings,
    routes_stock,
    routes_strategy,
    routes_tasks,
    routes_watchlist,
    routes_workspace,
    routes_setup,
)
from backend import paths
from backend.bootstrap import create_services
from backend.stock_domain.provider_router import provider_router


class _SpaCacheControlMiddleware(BaseHTTPMiddleware):
    """WKWebView / 浏览器会强缓存 index.html 与 /assets/*，导致改 CSS 后重启仍见旧皮。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            return response
        if path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def _frontend_index() -> Path | None:
    index = paths.frontend_dist() / "index.html"
    return index if index.is_file() else None


_STATIC_ASSET_SUFFIXES = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".map",
    ".mjs",
    ".png",
    ".svg",
    ".wasm",
    ".webp",
    ".woff",
    ".woff2",
}


def _is_static_asset(rel: str) -> bool:
    """Hashed build files must not fall through to index.html.

    A missing ``/assets/*.js`` that returns the SPA shell is served as
    ``text/html``. WKWebView then rejects the dynamic import with
    "'text/html' is not a valid JavaScript MIME type."
    """
    path = rel.split("?", 1)[0].split("#", 1)[0]
    if path.startswith("assets/"):
        return True
    return Path(path).suffix.lower() in _STATIC_ASSET_SUFFIXES


def _frontend_file(rel: str) -> Path | None:
    """Resolve a file under frontend/dist with path-traversal protection."""
    if not rel or rel.endswith("/"):
        return None
    dist = paths.frontend_dist().resolve()
    if not dist.is_dir():
        return None
    candidate = (dist / rel).resolve()
    try:
        candidate.relative_to(dist)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


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
    db_path: str | Path | None = None, files_root: str | Path | None = None
) -> FastAPI:
    # 缺省路径经 backend.paths 解析（支持 WORKBENCH_DATA_DIR，修 cwd 陷阱）；
    # 显式传参（测试）行为不变。
    services = create_services(
        db_path=db_path if db_path is not None else paths.default_db_path(),
        files_root=files_root if files_root is not None else paths.default_files_root(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await services.monitor_service.startup()
        await services.scheduler_service.startup()
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
            await services.scheduler_service.shutdown()
            await services.monitor_service.shutdown()
            await services.data_collector.shutdown()
            try:
                await services.channel_service.stop()
            except Exception:
                logging.getLogger("app").exception("channel service failed to stop")

    app = FastAPI(title="AI Stock Workbench", version="0.1.0", lifespan=lifespan)
    app.state.services = services
    app.add_middleware(_SpaCacheControlMiddleware)
    app.add_middleware(AccessAuthMiddleware)
    cors_origins = cors_origin_list()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["health"])
    def health(request: Request):
        public = {"status": "ok", "server_role": "workbench"}
        from backend.access_auth import configured_token

        if configured_token() and not getattr(request.state, "workbench_authorized", False):
            return public
        agent_runtime = app.state.services.copilot_service.deerflow.status().to_dict()
        from backend import service_cli

        return {
            "status": "ok",
            "mode": "single-user-local",
            "server_role": "workbench",
            "runtime": f"deerflow-adapter-{agent_runtime['active_client']}",
            "agent_runtime": agent_runtime,
            "stock_domain": "provider-router",
            "data_provider": provider_router.status().to_dict(),
            "data_dir": str(paths.data_dir().resolve()),
            "service_mode": "launchd" if service_cli.service_loaded() else "dev",
            "frontend_ready": _frontend_index() is not None,
        }

    @app.get("/app", include_in_schema=False)
    def app_shell():
        index = _frontend_index()
        if index is None:
            raise HTTPException(
                status_code=503,
                detail="frontend/dist missing; run: make build",
            )
        return FileResponse(index)

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
        routes_scheduled_tasks.router,
        routes_settings.router,
        routes_setup.router,
        routes_copilot.router,
        routes_channels.router,
        routes_workspace.router,
    ]:
        app.include_router(router)

    # 请求时解析 frontend/dist（勿仅在启动时 mount）：避免 dist 稍后构建完仍 404，
    # 以及 vite 构建清空目录窗口期与引导页跳转撞车。
    @app.get("/", include_in_schema=False)
    def spa_root():
        index = _frontend_index()
        if index is None:
            raise HTTPException(
                status_code=503,
                detail="frontend/dist missing; run: make build",
            )
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_static_or_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        found = _frontend_file(full_path)
        if found is not None:
            return FileResponse(found)
        if _is_static_asset(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        index = _frontend_index()
        if index is not None:
            return FileResponse(index)
        raise HTTPException(
            status_code=503,
            detail="frontend/dist missing; run: make build",
        )

    return app


def __getattr__(name: str):
    """Lazy module attribute (PEP 562): build the default app only when uvicorn
    actually asks for ``backend.app:app``.

    之前是模块级 ``app = create_app()``——任何 ``from backend.app import
    create_app``（比如整个测试套件）都会在默认路径上再建一套服务栈，
    pytest 全程握着 data/workbench.sqlite3 的连接，把真实后端的启动播种
    锁死（database is locked）。
    """
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from backend.schemas import StockDaily, StockQuote, now_iso
from backend.persistence.repositories import WorkbenchRepository
from backend.stock_domain.provider_router import provider_router

logger = logging.getLogger(__name__)

DEFAULT_COLLECTOR_INTERVAL_SECONDS = 1800  # 30 minutes
ENV_INTERVAL = "WORKBENCH_COLLECTOR_INTERVAL_SECONDS"
ENV_AUTO_START = "WORKBENCH_COLLECTOR_AUTO_START"


class DataCollectorService:
    """Background service that periodically collects live data for monitored stocks.

    Follows the same lifecycle pattern as MonitorService:
    - startup() / shutdown() called from FastAPI lifespan
    - Runs an asyncio.Task loop that polls on a configurable interval
    - Persists results via the repository (batch upsert for history)
    - Only collects for watchlist items with monitored=True
    - Skips degraded (mock/fallback) results
    """

    def __init__(self, repo: WorkbenchRepository) -> None:
        self.repo = repo
        self._loop_task: asyncio.Task[None] | None = None

    # ── Lifecycle ──────────────────────────────────────────────────

    async def startup(self) -> None:
        auto_start = os.environ.get(ENV_AUTO_START, "").strip().lower() in ("1", "true", "yes")
        if auto_start:
            logger.info("data_collector: auto-start enabled, starting collection loop")
            await self.start_loop()
        else:
            logger.info("data_collector: auto-start disabled (set %s=1 to enable)", ENV_AUTO_START)

    async def shutdown(self) -> None:
        await self.stop_loop()

    async def start_loop(self) -> None:
        if self.is_loop_running():
            return
        self._loop_task = asyncio.create_task(self._run_loop(), name="workbench-data-collector-loop")

    async def stop_loop(self) -> None:
        if not self._loop_task:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    def is_loop_running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    def interval_seconds(self) -> int:
        raw = os.environ.get(ENV_INTERVAL, "")
        try:
            return max(60, int(raw))
        except (ValueError, TypeError):
            return DEFAULT_COLLECTOR_INTERVAL_SECONDS

    # ── Loop ───────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._collect_once)
            except Exception as exc:
                logger.exception("data_collector: collection cycle failed: %s", exc)
            await asyncio.sleep(self.interval_seconds())

    def _collect_once(self) -> dict[str, Any]:
        """Collect data for all monitored watchlist items.
        Returns a summary dict (for testing/inspection).
        """
        summary: dict[str, Any] = {
            "checked": 0,
            "quotes": 0,
            "history_items": 0,
            "errors": [],
            "skipped_degraded": [],
        }
        items = self.repo.list_watchlist()
        monitored = [item for item in items if item.monitored]
        if not monitored:
            logger.debug("data_collector: no monitored stocks to collect")
            return summary

        for item in monitored:
            symbol = item.symbol
            summary["checked"] += 1
            try:
                count = self._collect_symbol(symbol)
                summary["history_items"] += count
                summary["quotes"] += 1
            except Exception as exc:
                summary["errors"].append({"symbol": symbol, "error": str(exc)})
                logger.warning("data_collector: collect %s failed: %s", symbol, exc)

        total_errors = len(summary["errors"])
        if summary["checked"] > 0:
            logger.info(
                "data_collector: %d stocks checked, %d quotes, %d history rows (%d errors)",
                summary["checked"],
                summary["quotes"],
                summary["history_items"],
                total_errors,
            )
        return summary

    def _collect_symbol(self, symbol: str) -> int:
        """Fetch and persist quote + recent history for one symbol.
        Returns the number of daily rows stored.
        """
        # Collect quote
        quote = provider_router.get_quote(symbol)
        if not quote.degraded:
            self.repo.upsert_stock_quote(StockQuote(
                symbol=symbol,
                last=quote.last,
                change_pct=quote.change_pct,
                volume=getattr(quote, "volume", 0.0),
                amount=getattr(quote, "amount", 0.0),
                source=quote.source,
                provider=quote.source,
                updated_at=quote.updated_at or now_iso(),
            ))

        # Collect recent history (1 trading day = latest close)
        result = provider_router.get_history(symbol, days=5)
        if result.get("degraded"):
            return 0
        items_raw = result.get("items", [])
        if not items_raw:
            return 0

        daily_items = [
            StockDaily(
                symbol=symbol,
                trade_date=str(item.get("date", "")),
                open=float(item.get("open", 0)),
                high=float(item.get("high", 0)),
                low=float(item.get("low", 0)),
                close=float(item.get("close", 0)),
                volume=float(item.get("volume", 0)),
                amount=float(item.get("amount", 0)),
                source=result.get("source", ""),
            )
            for item in items_raw
        ]
        return self.repo.batch_upsert_stock_daily(daily_items)

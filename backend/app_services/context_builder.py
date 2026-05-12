from __future__ import annotations

from datetime import datetime, timezone

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AIState, HoldingInfo, LatestReport, PriceSnapshot, StockContext, StockRelation
from backend.stock_domain.catalog import get_stock, normalize_symbol, search_stocks
from backend.stock_domain.quote_tools import get_realtime_quote


class ContextBuilder:
    def __init__(self, repo: WorkbenchRepository) -> None:
        self.repo = repo

    def build_stock_context(self, symbol: str) -> StockContext:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            matches = search_stocks(symbol)
            stock = matches[0] if matches else None
            normalized = str(stock["symbol"]) if stock else normalized
        if not stock:
            raise KeyError(f"unknown stock: {symbol}")

        watchlist = {item.symbol.upper(): item for item in self.repo.list_watchlist()}
        holdings = {item.symbol.upper(): item for item in self.repo.list_holdings()}
        holding = holdings.get(normalized)
        watch_item = watchlist.get(normalized)
        reports = self.repo.list_reports(symbol=normalized, limit=1)
        latest = reports[0] if reports else None

        price = get_realtime_quote(normalized)
        if price is None:
            price = PriceSnapshot(
                last=0.0,
                change_pct=0.0,
                updated_at=datetime.now(timezone.utc).isoformat(),
                source="unavailable",
                degraded=True,
                degraded_reason="quote unavailable",
            )

        return StockContext(
            symbol=normalized,
            name=str(stock["name"]),
            market=str(stock["market"]),
            industry=str(stock["industry"]),
            sector=str(stock["sector"]),
            price=price,
            relation=StockRelation(
                in_watchlist=watch_item is not None,
                in_holdings=holding is not None,
                monitored=bool(watch_item.monitored) if watch_item else False,
            ),
            holding=HoldingInfo(
                weight_pct=holding.weight_pct if holding else 0,
                quantity=holding.quantity if holding else 0,
                market_value=holding.market_value if holding else 0,
                cost=holding.cost if holding else None,
                pnl_pct=holding.pnl_pct if holding else None,
            ),
            ai_state=AIState(
                score=int(stock["score"]),
                risk_label=str(stock["risk_label"]),
                stance=str(stock["stance"]),
                confidence=str(stock["confidence"]),
            ),
            latest_report=LatestReport(
                report_id=latest.report_id if latest else None,
                generated_at=latest.created_at if latest else None,
            ),
        )

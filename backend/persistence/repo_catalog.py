from __future__ import annotations

import json
import sqlite3
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from backend.schemas import (
    AgentTask,
    AuthorityLevel,
    AuditLog,
    BacktestRun,
    CopilotRunLog,
    CopilotMessage,
    CopilotSession,
    DecisionJournalEntry,
    HoldingPosition,
    MonitorRule,
    MonitorStatus,
    now_iso,
    PaperOrder,
    PaperPortfolioSnapshot,
    PreTradeReview,
    ProviderCallLog,
    Report,
    RuntimeMetricSnapshot,
    ReviewInboxState,
    ReportQualityCheck,
    ReportTemplate,
    RebalanceDraft,
    RiskPolicy,
    StockDaily,
    StockFinancial,
    StockMaster,
    StockQuote,
    StrategySpec,
    ToolExecution,
    WatchlistItem,
    EventContext,
    model_to_dict,
    now_iso,
)
from backend.persistence.repo_base import _json, _loads

class CatalogRepoMixin:
    def list_watchlist(self) -> List[WatchlistItem]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM watchlist_item ORDER BY position, symbol"
            ).fetchall()
        return [
            WatchlistItem(
                symbol=row["symbol"],
                name=row["name"],
                group=row["group_name"],
                tags=json.loads(row["tags"] or "[]"),
                monitored=bool(row["monitored"]),
            )
            for row in rows
        ]

    def upsert_watchlist_item(self, item: WatchlistItem) -> WatchlistItem:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO watchlist_item(symbol, name, group_name, tags, monitored, position)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT MAX(position) FROM watchlist_item), 0) + 1)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  group_name=excluded.group_name,
                  tags=excluded.tags,
                  monitored=excluded.monitored
                """,
                (
                    item.symbol.upper(),
                    item.name,
                    item.group,
                    _json(item.tags),
                    int(item.monitored),
                ),
            )
            self.conn.commit()
        return item

    def update_watchlist_position(self, symbol: str, pos: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE watchlist_item SET position = ? WHERE symbol = ?",
                (pos, symbol.upper()),
            )
            self.conn.commit()

    def list_watchlist_groups(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM watchlist_group ORDER BY sort_order, name"
            ).fetchall()
        return [{"name": r["name"], "color": r["color"], "sort_order": r["sort_order"]} for r in rows]

    def upsert_watchlist_group(self, name: str, color: str = "#6366f1") -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO watchlist_group(name, color, sort_order)
                   VALUES (?, ?, COALESCE((SELECT MAX(sort_order) FROM watchlist_group), 0) + 1)
                   ON CONFLICT(name) DO UPDATE SET color=excluded.color""",
                (name, color),
            )
            self.conn.commit()

    def rename_watchlist_group(self, old_name: str, new_name: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE watchlist_group SET name = ? WHERE name = ?", (new_name, old_name))
            self.conn.execute("UPDATE watchlist_item SET group_name = ? WHERE group_name = ?", (new_name, old_name))
            self.conn.commit()

    def delete_watchlist_group(self, name: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE watchlist_item SET group_name = '默认' WHERE group_name = ?", (name,))
            self.conn.execute("DELETE FROM watchlist_group WHERE name = ?", (name,))
            self.conn.commit()

    def update_group_sort(self, name: str, sort_order: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE watchlist_group SET sort_order = ? WHERE name = ?",
                (sort_order, name),
            )
            self.conn.commit()

    def delete_watchlist_item(self, symbol: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM watchlist_item WHERE symbol = ?", (symbol.upper(),)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def list_holdings(self) -> List[HoldingPosition]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM holding_position ORDER BY weight_pct DESC"
            ).fetchall()
        return [HoldingPosition(**dict(row)) for row in rows]

    def upsert_holding(self, position: HoldingPosition) -> HoldingPosition:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO holding_position(symbol, name, quantity, market_value, weight_pct, cost, pnl_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  quantity=excluded.quantity,
                  market_value=excluded.market_value,
                  weight_pct=excluded.weight_pct,
                  cost=excluded.cost,
                  pnl_pct=excluded.pnl_pct
                """,
                (
                    position.symbol.upper(),
                    position.name,
                    position.quantity,
                    position.market_value,
                    position.weight_pct,
                    position.cost,
                    position.pnl_pct,
                ),
            )
            self.conn.commit()
        return position

    def list_stock_master(self, *, active_only: bool = True) -> List[StockMaster]:
        with self._lock:
            if active_only:
                rows = self.conn.execute(
                    "SELECT * FROM stock_master WHERE is_active = 1 ORDER BY symbol"
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM stock_master ORDER BY symbol"
                ).fetchall()
        result: List[StockMaster] = []
        for row in rows:
            result.append(
                StockMaster(
                    symbol=row["symbol"],
                    name=row["name"],
                    market=row["market"],
                    industry=row["industry"] or "",
                    sector=row["sector"] or "",
                    aliases=json.loads(row["aliases"] or "[]"),
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
        return result

    def get_stock_master(self, symbol: str) -> Optional[StockMaster]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_master WHERE symbol = ?", (symbol,)
            ).fetchone()
        if not row:
            return None
        return StockMaster(
            symbol=row["symbol"],
            name=row["name"],
            market=row["market"],
            industry=row["industry"] or "",
            sector=row["sector"] or "",
            aliases=json.loads(row["aliases"] or "[]"),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def search_stock_master(self, query: str) -> List[StockMaster]:
        q = query.strip().lower()
        if not q:
            return self.list_stock_master()
        all_stocks = self.list_stock_master(active_only=True)
        result: List[StockMaster] = []
        for s in all_stocks:
            haystack = " ".join(
                [
                    s.symbol,
                    s.name,
                    s.market,
                ]
                + s.aliases
            ).lower()
            if q in haystack:
                result.append(s)
        return result

    def upsert_stock_master(self, item: StockMaster) -> StockMaster:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_master(symbol, name, market, industry, sector, aliases, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  market=excluded.market,
                  industry=excluded.industry,
                  sector=excluded.sector,
                  aliases=excluded.aliases,
                  is_active=excluded.is_active,
                  updated_at=excluded.updated_at
                """,
                (
                    item.symbol.upper(),
                    item.name,
                    item.market,
                    item.industry,
                    item.sector,
                    json.dumps(item.aliases, ensure_ascii=False),
                    int(item.is_active),
                    item.created_at,
                    item.updated_at,
                ),
            )
            self.conn.commit()
        return item

    def batch_upsert_stock_master(self, items: List[StockMaster]) -> int:
        if not items:
            return 0
        from backend.schemas import now_iso

        now_val = now_iso()
        placeholders = ",".join("(?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in items)
        flat_params: list[Any] = []
        for item in items:
            flat_params.extend(
                (
                    item.symbol.upper(),
                    item.name,
                    item.market,
                    item.industry,
                    item.sector,
                    json.dumps(item.aliases, ensure_ascii=False),
                    int(item.is_active),
                    now_val,
                    now_val,
                )
            )
        sql = f"""
            INSERT INTO stock_master(symbol, name, market, industry, sector, aliases, is_active, created_at, updated_at)
            VALUES {placeholders}
            ON CONFLICT(symbol) DO UPDATE SET
              name=excluded.name,
              market=excluded.market,
              industry=excluded.industry,
              sector=excluded.sector,
              aliases=excluded.aliases,
              is_active=excluded.is_active,
              updated_at=excluded.updated_at
        """
        with self._lock:
            self.conn.execute(sql, flat_params)
            self.conn.commit()
        return len(items)

    # ── Stock Daily ─────────────────────────────────────────────────

    def upsert_stock_daily(self, item: StockDaily) -> StockDaily:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_daily(symbol, trade_date, open, high, low, close, volume, amount, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  amount=excluded.amount,
                  source=excluded.source
                """,
                (
                    item.symbol.upper(),
                    item.trade_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.amount,
                    item.source,
                    item.created_at,
                ),
            )
            self.conn.commit()
        return item

    def batch_upsert_stock_daily(self, items: List[StockDaily]) -> int:
        """Upsert many stock_daily rows in a single transaction.
        Returns the number of rows inserted/updated.
        """
        if not items:
            return 0
        placeholders = ",".join(
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))" for _ in items
        )
        flat_params: list[Any] = []
        for item in items:
            flat_params.extend(
                (
                    item.symbol.upper(),
                    item.trade_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.amount,
                    item.source,
                )
            )
        sql = f"""
            INSERT INTO stock_daily(symbol, trade_date, open, high, low, close, volume, amount, source, created_at)
            VALUES {placeholders}
            ON CONFLICT(symbol, trade_date) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume,
              amount=excluded.amount,
              source=excluded.source
        """
        with self._lock:
            self.conn.execute(sql, flat_params)
            self.conn.commit()
        return len(items)

    def list_stock_daily(
        self,
        symbol: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 90,
    ) -> List[StockDaily]:
        query = "SELECT * FROM stock_daily WHERE symbol = ?"
        params: List[Any] = [symbol.upper()]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            StockDaily(
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                amount=row["amount"],
                source=row["source"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_stock_daily(self, symbol: str, trade_date: str) -> Optional[StockDaily]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_daily WHERE symbol = ? AND trade_date = ?",
                (symbol.upper(), trade_date),
            ).fetchone()
        if not row:
            return None
        return StockDaily(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            amount=row["amount"],
            source=row["source"] or "",
            created_at=row["created_at"],
        )

    def count_stock_daily(self, symbol: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM stock_daily WHERE symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        return row["cnt"] if row else 0

    # ── Stock Quote ─────────────────────────────────────────────────

    def upsert_stock_quote(self, item: StockQuote) -> StockQuote:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_quote(symbol, last, change_pct, volume, amount, source, provider, hit_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  last=excluded.last,
                  change_pct=excluded.change_pct,
                  volume=excluded.volume,
                  amount=excluded.amount,
                  source=excluded.source,
                  provider=excluded.provider,
                  hit_count=excluded.hit_count,
                  updated_at=excluded.updated_at
                """,
                (
                    item.symbol.upper(),
                    item.last,
                    item.change_pct,
                    item.volume,
                    item.amount,
                    item.source,
                    item.provider,
                    item.hit_count,
                    item.updated_at,
                ),
            )
            self.conn.commit()
        return item

    def list_stock_quotes(self) -> list[StockQuote]:
        """Return all cached stock quotes (for staleness checks)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM stock_quote ORDER BY symbol"
            ).fetchall()
        return [
            StockQuote(
                symbol=row["symbol"],
                last=row["last"],
                change_pct=row["change_pct"],
                volume=row["volume"],
                amount=row["amount"],
                source=row["source"] or "",
                provider=row["provider"] or "",
                hit_count=row["hit_count"] if row["hit_count"] is not None else 0,
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_stock_quote(self, symbol: str) -> Optional[StockQuote]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_quote WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if not row:
            return None
        return StockQuote(
            symbol=row["symbol"],
            last=row["last"],
            change_pct=row["change_pct"],
            volume=row["volume"],
            amount=row["amount"],
            source=row["source"] or "",
            provider=row.get("provider", "") or "",
            hit_count=row.get("hit_count", 0) if row.get("hit_count") is not None else 0,
            updated_at=row["updated_at"],
        )

    # ── Stock Financial ─────────────────────────────────────────────

    def upsert_stock_financial(self, item: StockFinancial) -> StockFinancial:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_financial(symbol, report_date, report_type, revenue, profit, total_assets, total_liabilities, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type) DO UPDATE SET
                  revenue=excluded.revenue,
                  profit=excluded.profit,
                  total_assets=excluded.total_assets,
                  total_liabilities=excluded.total_liabilities,
                  payload=excluded.payload
                """,
                (
                    item.symbol.upper(),
                    item.report_date,
                    item.report_type,
                    item.revenue,
                    item.profit,
                    item.total_assets,
                    item.total_liabilities,
                    json.dumps(item.payload, ensure_ascii=False),
                    item.created_at,
                ),
            )
            self.conn.commit()
        return item

    def list_stock_financial(
        self, symbol: str, *, report_type: str | None = None
    ) -> List[StockFinancial]:
        query = "SELECT * FROM stock_financial WHERE symbol = ?"
        params: List[Any] = [symbol.upper()]
        if report_type:
            query += " AND report_type = ?"
            params.append(report_type)
        query += " ORDER BY report_date DESC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            StockFinancial(
                symbol=row["symbol"],
                report_date=row["report_date"],
                report_type=row["report_type"],
                revenue=row["revenue"],
                profit=row["profit"],
                total_assets=row["total_assets"],
                total_liabilities=row["total_liabilities"],
                payload=json.loads(row["payload"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ── Capability Cache ────────────────────────────────────────────
    def upsert_capability_cache(
        self, capability: str, payload: dict, symbol: str = ""
    ) -> None:
        from backend.schemas import now_iso

        now_val = now_iso()
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO capability_cache(capability, symbol, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(capability, symbol) DO UPDATE SET
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (capability, symbol, payload_str, now_val),
            )
            self.conn.commit()

    def get_capability_cache(self, capability: str, symbol: str = "") -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM capability_cache WHERE capability = ? AND symbol = ?",
                (capability, symbol),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

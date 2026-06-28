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

class TradingRepoMixin:
    def save_rebalance_draft(self, draft: RebalanceDraft) -> RebalanceDraft:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO rebalance_draft(
                  draft_id, symbol, status, authority_level, target_weight_pct, valid_until, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                  symbol=excluded.symbol,
                  status=excluded.status,
                  authority_level=excluded.authority_level,
                  target_weight_pct=excluded.target_weight_pct,
                  valid_until=excluded.valid_until,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    draft.draft_id,
                    draft.symbol,
                    draft.status.value,
                    draft.authority_level.value,
                    draft.target_weight_pct,
                    draft.valid_until,
                    draft.created_at,
                    draft.updated_at,
                    _json(draft),
                ),
            )
            self.conn.commit()
        return draft

    def get_rebalance_draft(self, draft_id: str) -> Optional[RebalanceDraft]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM rebalance_draft WHERE draft_id = ?", (draft_id,)
            ).fetchone()
        return RebalanceDraft(**_loads(row["payload"])) if row else None

    def list_rebalance_drafts(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[RebalanceDraft]:
        query = "SELECT payload FROM rebalance_draft"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, draft_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [RebalanceDraft(**_loads(row["payload"])) for row in rows]

    def save_pre_trade_review(self, review: PreTradeReview) -> PreTradeReview:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO pre_trade_review(
                  review_id, source_draft_id, symbol, status, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                  source_draft_id=excluded.source_draft_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    review.review_id,
                    review.source_draft_id,
                    review.symbol,
                    review.status.value,
                    review.created_at,
                    _json(review),
                ),
            )
            self.conn.commit()
        return review

    def get_pre_trade_review(self, review_id: str) -> Optional[PreTradeReview]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM pre_trade_review WHERE review_id = ?", (review_id,)
            ).fetchone()
        return PreTradeReview(**_loads(row["payload"])) if row else None

    def list_pre_trade_reviews(
        self,
        *,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[PreTradeReview]:
        query = "SELECT payload FROM pre_trade_review"
        clauses: list[str] = []
        params: list[Any] = []
        if draft_id is not None:
            clauses.append("source_draft_id = ?")
            params.append(draft_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, review_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PreTradeReview(**_loads(row["payload"])) for row in rows]

    def save_paper_order(self, order: PaperOrder) -> PaperOrder:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO paper_order(
                  order_id, review_id, source_draft_id, symbol, status, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                  review_id=excluded.review_id,
                  source_draft_id=excluded.source_draft_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    order.order_id,
                    order.review_id,
                    order.source_draft_id,
                    order.symbol,
                    order.status.value,
                    order.created_at,
                    _json(order),
                ),
            )
            self.conn.commit()
        return order

    def get_paper_order(self, order_id: str) -> Optional[PaperOrder]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM paper_order WHERE order_id = ?", (order_id,)
            ).fetchone()
        return PaperOrder(**_loads(row["payload"])) if row else None

    def list_paper_orders(
        self,
        *,
        review_id: str | None = None,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[PaperOrder]:
        query = "SELECT payload FROM paper_order"
        clauses: list[str] = []
        params: list[Any] = []
        if review_id is not None:
            clauses.append("review_id = ?")
            params.append(review_id)
        if draft_id is not None:
            clauses.append("source_draft_id = ?")
            params.append(draft_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, order_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PaperOrder(**_loads(row["payload"])) for row in rows]

    def save_paper_portfolio_snapshot(
        self, snapshot: PaperPortfolioSnapshot
    ) -> PaperPortfolioSnapshot:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO paper_portfolio_snapshot(
                  snapshot_id, baseline_id, as_of, degraded, market_value, cash_estimate,
                  equity_estimate, pnl_estimate, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.baseline_id,
                    snapshot.as_of,
                    int(snapshot.degraded),
                    snapshot.market_value,
                    snapshot.cash_estimate,
                    snapshot.equity_estimate,
                    snapshot.pnl_estimate,
                    snapshot.created_at,
                    _json(snapshot),
                ),
            )
            self.conn.commit()
        return snapshot

    def get_paper_portfolio_snapshot(
        self, snapshot_id: str
    ) -> Optional[PaperPortfolioSnapshot]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM paper_portfolio_snapshot WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return PaperPortfolioSnapshot(**_loads(row["payload"])) if row else None

    def list_paper_portfolio_snapshots(
        self,
        *,
        baseline_id: str | None = None,
        limit: int | None = 50,
    ) -> List[PaperPortfolioSnapshot]:
        query = "SELECT payload FROM paper_portfolio_snapshot"
        clauses: list[str] = []
        params: list[Any] = []
        if baseline_id is not None:
            clauses.append("baseline_id = ?")
            params.append(baseline_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY as_of DESC, created_at DESC, snapshot_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PaperPortfolioSnapshot(**_loads(row["payload"])) for row in rows]

    def save_decision_journal_entry(
        self, entry: DecisionJournalEntry
    ) -> DecisionJournalEntry:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO decision_journal_entry(
                  entry_id, decision_id, draft_id, review_id, paper_order_id, snapshot_id,
                  report_id, symbol, status, source_type, closed_at, close_note, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                  decision_id=excluded.decision_id,
                  draft_id=excluded.draft_id,
                  review_id=excluded.review_id,
                  paper_order_id=excluded.paper_order_id,
                  snapshot_id=excluded.snapshot_id,
                  report_id=excluded.report_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  source_type=excluded.source_type,
                  closed_at=excluded.closed_at,
                  close_note=excluded.close_note,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    entry.entry_id,
                    entry.decision_id,
                    entry.draft_id,
                    entry.review_id,
                    entry.paper_order_id,
                    entry.snapshot_id,
                    entry.report_id,
                    entry.symbol,
                    entry.status,
                    entry.source_type,
                    entry.closed_at,
                    entry.close_note,
                    entry.created_at,
                    entry.updated_at,
                    _json(entry),
                ),
            )
            self.conn.commit()
        return entry

    def get_decision_journal_entry(
        self, entry_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_decision_id(
        self, decision_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_draft_id(
        self, draft_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_review_id(
        self, review_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_paper_order_id(
        self, paper_order_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE paper_order_id = ?",
                (paper_order_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_snapshot_id(
        self, snapshot_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def list_decision_journal_entries(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        limit: int | None = 50,
    ) -> List[DecisionJournalEntry]:
        query = "SELECT payload FROM decision_journal_entry"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, created_at DESC, entry_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [DecisionJournalEntry(**_loads(row["payload"])) for row in rows]

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

class StrategyRepoMixin:
    def save_strategy_spec(self, spec: StrategySpec) -> StrategySpec:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO strategy_spec(
                  strategy_id, name, strategy_type, enabled, risk_level, tags, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                  name=excluded.name,
                  strategy_type=excluded.strategy_type,
                  enabled=excluded.enabled,
                  risk_level=excluded.risk_level,
                  tags=excluded.tags,
                  payload=excluded.payload,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at
                """,
                (
                    spec.strategy_id,
                    spec.name,
                    spec.strategy_type,
                    int(spec.enabled),
                    spec.risk_level,
                    _json(spec.tags),
                    _json(spec),
                    spec.created_at,
                    spec.updated_at,
                ),
            )
            self.conn.commit()
        return spec

    def list_strategy_specs(self, enabled: bool | None = None) -> List[StrategySpec]:
        query = "SELECT payload FROM strategy_spec"
        params: list[Any] = []
        if enabled is not None:
            query += " WHERE enabled = ?"
            params.append(int(enabled))
        query += " ORDER BY updated_at DESC, strategy_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [StrategySpec(**_loads(row["payload"])) for row in rows]

    def get_strategy_spec(self, strategy_id: str) -> Optional[StrategySpec]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM strategy_spec WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return StrategySpec(**_loads(row["payload"])) if row else None

    def delete_strategy_spec(self, strategy_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM strategy_spec WHERE strategy_id = ?", (strategy_id,)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO backtest_run(
                  run_id, strategy_id, strategy_name, strategy_type, degraded, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.strategy_id,
                    run.strategy_name,
                    run.strategy_type,
                    int(run.degraded),
                    run.created_at,
                    _json(run),
                ),
            )
            self.conn.commit()
        return run

    def list_backtest_runs(
        self, strategy_id: str | None = None, limit: int = 20
    ) -> List[BacktestRun]:
        query = "SELECT payload FROM backtest_run"
        params: list[Any] = []
        if strategy_id is not None:
            query += " WHERE strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY created_at DESC, run_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [BacktestRun(**_loads(row["payload"])) for row in rows]

    def get_backtest_run(self, run_id: str) -> Optional[BacktestRun]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM backtest_run WHERE run_id = ?", (run_id,)
            ).fetchone()
        return BacktestRun(**_loads(row["payload"])) if row else None

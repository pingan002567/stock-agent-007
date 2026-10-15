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

class ConfigRepoMixin:
    def save_audit(self, log: AuditLog) -> AuditLog:
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit_log(audit_id, payload, created_at) VALUES (?, ?, ?)",
                (log.audit_id, _json(log), log.created_at),
            )
            self.conn.commit()
        return log

    def list_audit(self, limit: int = 100) -> List[AuditLog]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AuditLog(**_loads(row["payload"])) for row in rows]

    def save_tool_execution(self, execution: ToolExecution) -> ToolExecution:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO tool_execution(
                  execution_id, task_id, run_id, call_id, tool, domain, status, authority_level,
                  arguments, source_mode, evidence_refs, result_summary, error, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                  task_id=excluded.task_id,
                  run_id=excluded.run_id,
                  call_id=excluded.call_id,
                  tool=excluded.tool,
                  domain=excluded.domain,
                  status=excluded.status,
                  authority_level=excluded.authority_level,
                  arguments=excluded.arguments,
                  source_mode=excluded.source_mode,
                  evidence_refs=excluded.evidence_refs,
                  result_summary=excluded.result_summary,
                  error=excluded.error,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    execution.execution_id,
                    execution.task_id,
                    execution.run_id,
                    execution.call_id,
                    execution.tool,
                    execution.domain,
                    execution.status,
                    execution.authority_level,
                    _json(execution.arguments),
                    execution.source_mode,
                    _json(execution.evidence_refs),
                    execution.result_summary,
                    execution.error,
                    _json(execution),
                    execution.created_at,
                ),
            )
            self.conn.commit()
        return execution

    def list_tool_executions(
        self, task_id: str | None = None, run_id: str | None = None, limit: int = 100
    ) -> List[ToolExecution]:
        query = "SELECT payload FROM tool_execution"
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [ToolExecution(**_loads(row["payload"])) for row in rows]

    def save_review_inbox_state(self, state: ReviewInboxState) -> ReviewInboxState:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO review_inbox_state(item_key, status, snoozed_until, note, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                  status=excluded.status,
                  snoozed_until=excluded.snoozed_until,
                  note=excluded.note,
                  updated_at=excluded.updated_at
                """,
                (
                    state.item_key,
                    state.status.value,
                    state.snoozed_until,
                    state.note,
                    state.updated_at,
                ),
            )
            self.conn.commit()
        return state

    def get_review_inbox_state(self, item_key: str) -> Optional[ReviewInboxState]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT item_key, status, snoozed_until, note, updated_at
                FROM review_inbox_state
                WHERE item_key = ?
                """,
                (item_key,),
            ).fetchone()
        return ReviewInboxState(**dict(row)) if row else None

    def list_review_inbox_states(self) -> List[ReviewInboxState]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT item_key, status, snoozed_until, note, updated_at
                FROM review_inbox_state
                ORDER BY updated_at DESC, item_key DESC
                """
            ).fetchall()
        return [ReviewInboxState(**dict(row)) for row in rows]

    def set_config(self, key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO app_config(key, payload)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET payload=excluded.payload
                """,
                (key, _json(payload)),
            )
            self.conn.commit()
        return payload

    def get_config(
        self, key: str, default: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM app_config WHERE key = ?", (key,)
            ).fetchone()
        return _loads(row["payload"]) if row else (default or {})

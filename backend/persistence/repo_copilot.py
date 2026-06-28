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

class CopilotRepoMixin:
    def save_task(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO agent_task(task_id, payload, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload
                """,
                (task.task_id, _json(task), task.created_at),
            )
            self.conn.commit()
        return task

    def save_provider_call_log(self, log: ProviderCallLog) -> ProviderCallLog:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO provider_call_log(
                  call_id, capability, market, symbol, provider, fallback_provider,
                  status, degraded_reason, duration_ms, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.call_id,
                    log.capability,
                    log.market,
                    log.symbol,
                    log.provider,
                    log.fallback_provider,
                    log.status,
                    log.degraded_reason,
                    log.duration_ms,
                    log.created_at,
                    _json(log.payload),
                ),
            )
            self.conn.commit()
        return log

    def list_provider_call_logs(
        self, *, limit: int = 100, capability: str | None = None
    ) -> List[ProviderCallLog]:
        query = "SELECT * FROM provider_call_log"
        params: list[Any] = []
        if capability:
            query += " WHERE capability = ?"
            params.append(capability)
        query += " ORDER BY created_at DESC, call_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            ProviderCallLog(
                call_id=row["call_id"],
                capability=row["capability"],
                market=row["market"],
                symbol=row["symbol"],
                provider=row["provider"],
                fallback_provider=row["fallback_provider"],
                status=row["status"],
                degraded_reason=row["degraded_reason"],
                duration_ms=row["duration_ms"],
                created_at=row["created_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def cleanup_provider_call_logs(self, *, keep_days: int = 7) -> int:
        import datetime as _dt
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=keep_days)).isoformat()
        with self._lock:
            cur = self.conn.execute("DELETE FROM provider_call_log WHERE created_at < ?", (cutoff,))
            return cur.rowcount

    def save_copilot_run_log(self, log: CopilotRunLog) -> CopilotRunLog:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_run_log(
                  run_id, session_id, task_id, mode, active_client, model_name, status,
                  error_category, runtime_error, tool_call_count, usage_input_tokens,
                  usage_output_tokens, cost, latency_ms, started_at,
                  created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  session_id=excluded.session_id,
                  task_id=excluded.task_id,
                  mode=excluded.mode,
                  active_client=excluded.active_client,
                  model_name=excluded.model_name,
                  status=excluded.status,
                  error_category=excluded.error_category,
                  runtime_error=excluded.runtime_error,
                  tool_call_count=excluded.tool_call_count,
                  usage_input_tokens=excluded.usage_input_tokens,
                  usage_output_tokens=excluded.usage_output_tokens,
                  cost=excluded.cost,
                  latency_ms=excluded.latency_ms,
                  started_at=excluded.started_at,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    log.run_id,
                    log.session_id,
                    log.task_id,
                    log.mode,
                    log.active_client,
                    log.model_name,
                    log.status,
                    log.error_category,
                    log.runtime_error,
                    log.tool_call_count,
                    log.usage_input_tokens,
                    log.usage_output_tokens,
                    log.cost,
                    log.latency_ms,
                    log.started_at,
                    log.created_at,
                    log.updated_at,
                    _json(log.payload),
                ),
            )
            self.conn.commit()
        return log

    def list_copilot_run_logs(
        self, *, limit: int = 100, status: str | None = None
    ) -> List[CopilotRunLog]:
        query = "SELECT * FROM copilot_run_log"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, run_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            CopilotRunLog(
                run_id=row["run_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                mode=row["mode"],
                active_client=row["active_client"],
                model_name=row["model_name"],
                status=row["status"],
                error_category=row["error_category"],
                runtime_error=row["runtime_error"],
                tool_call_count=row["tool_call_count"],
                usage_input_tokens=row["usage_input_tokens"],
                usage_output_tokens=row["usage_output_tokens"],
                cost=row["cost"],
                latency_ms=row["latency_ms"],
                started_at=row["started_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def get_copilot_run_log(self, run_id: str) -> Optional[CopilotRunLog]:
        rows = self.list_copilot_run_logs(limit=1)
        row = next((item for item in rows if item.run_id == run_id), None)
        if row is not None:
            return row
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM copilot_run_log WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return CopilotRunLog(
            run_id=row["run_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            mode=row["mode"],
            active_client=row["active_client"],
            model_name=row["model_name"],
            status=row["status"],
            error_category=row["error_category"],
            runtime_error=row["runtime_error"],
            tool_call_count=row["tool_call_count"],
            usage_input_tokens=row["usage_input_tokens"],
            usage_output_tokens=row["usage_output_tokens"],
            cost=row["cost"],
            latency_ms=row["latency_ms"],
            started_at=row["started_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload=_loads(row["payload"]),
        )

    def save_runtime_metric_snapshot(
        self, snapshot: RuntimeMetricSnapshot
    ) -> RuntimeMetricSnapshot:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO runtime_metric_snapshot(snapshot_id, created_at, payload)
                VALUES (?, ?, ?)
                """,
                (snapshot.snapshot_id, snapshot.created_at, _json(snapshot.payload)),
            )
            self.conn.commit()
        return snapshot

    def list_runtime_metric_snapshots(
        self, *, limit: int = 50
    ) -> List[RuntimeMetricSnapshot]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM runtime_metric_snapshot ORDER BY created_at DESC, snapshot_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            RuntimeMetricSnapshot(
                snapshot_id=row["snapshot_id"],
                created_at=row["created_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def list_tasks(self) -> List[AgentTask]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM agent_task ORDER BY created_at DESC"
            ).fetchall()
        return [AgentTask(**_loads(row["payload"])) for row in rows]

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM agent_task WHERE task_id = ?", (task_id,)
            ).fetchone()
        return AgentTask(**_loads(row["payload"])) if row else None

    def get_task_by_run_id(self, run_id: str) -> Optional[AgentTask]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM agent_task WHERE json_extract(payload, '$.run_id') = ? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return AgentTask(**_loads(row["payload"])) if row else None

    def save_copilot_session(self, session: CopilotSession) -> CopilotSession:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_session(
                  session_id, title, status, current_page, anchor_symbol, authority_level,
                  created_at, updated_at, last_message_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  title=excluded.title,
                  status=excluded.status,
                  current_page=excluded.current_page,
                  anchor_symbol=excluded.anchor_symbol,
                  authority_level=excluded.authority_level,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  last_message_at=excluded.last_message_at
                """,
                (
                    session.session_id,
                    session.title,
                    session.status,
                    session.current_page,
                    session.anchor_symbol,
                    session.authority_level.value,
                    session.created_at,
                    session.updated_at,
                    session.last_message_at,
                ),
            )
            self.conn.commit()
        return session

    def list_copilot_sessions(self, limit: int | None = 50) -> List[CopilotSession]:
        query = "SELECT * FROM copilot_session ORDER BY COALESCE(last_message_at, updated_at) DESC, created_at DESC"
        params: list[Any] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_copilot_session(row) for row in rows]

    def delete_copilot_session(self, session_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM copilot_message WHERE session_id = ?", (session_id,)
            )
            self.conn.execute(
                "DELETE FROM copilot_session WHERE session_id = ?", (session_id,)
            )
            self.conn.commit()

    def get_copilot_session(self, session_id: str) -> Optional[CopilotSession]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM copilot_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._row_to_copilot_session(row) if row else None

    def save_copilot_message(self, message: CopilotMessage) -> CopilotMessage:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_message(
                  message_id, session_id, role, kind, text, page, symbol,
                  run_id, task_id, client_message_id, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                  session_id=excluded.session_id,
                  role=excluded.role,
                  kind=excluded.kind,
                  text=excluded.text,
                  page=excluded.page,
                  symbol=excluded.symbol,
                  run_id=excluded.run_id,
                  task_id=excluded.task_id,
                  client_message_id=excluded.client_message_id,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.role,
                    message.kind,
                    message.text,
                    message.page,
                    message.symbol,
                    message.run_id,
                    message.task_id,
                    message.client_message_id,
                    message.created_at,
                    _json(message.payload),
                ),
            )
            session = self.get_copilot_session(message.session_id)
            if session:
                updated = session.model_copy(
                    update={
                        "current_page": message.page or session.current_page,
                        "anchor_symbol": message.symbol or session.anchor_symbol,
                        "updated_at": message.created_at,
                        "last_message_at": message.created_at,
                    }
                )
                self.conn.execute(
                    """
                    UPDATE copilot_session
                    SET current_page = ?, anchor_symbol = ?, updated_at = ?, last_message_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        updated.current_page,
                        updated.anchor_symbol,
                        updated.updated_at,
                        updated.last_message_at,
                        updated.session_id,
                    ),
                )
            self.conn.commit()
        return message

    def list_copilot_messages(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> List[CopilotMessage]:
        query = "SELECT * FROM copilot_message WHERE session_id = ?"
        params: list[Any] = [session_id]
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at ASC, message_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_copilot_message(row) for row in rows]

    def get_copilot_user_message_by_run_id(
        self, run_id: str
    ) -> Optional[CopilotMessage]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM copilot_message
                WHERE run_id = ? AND role = 'user'
                ORDER BY created_at ASC, message_id ASC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_copilot_message(row) if row else None

    def list_copilot_run_messages(self, run_id: str) -> List[CopilotMessage]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM copilot_message WHERE run_id = ? ORDER BY created_at ASC, message_id ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_copilot_message(row) for row in rows]

    def _row_to_copilot_session(self, row: sqlite3.Row) -> CopilotSession:
        return CopilotSession(
            session_id=row["session_id"],
            title=row["title"],
            status=row["status"],
            current_page=row["current_page"],
            anchor_symbol=row["anchor_symbol"],
            authority_level=AuthorityLevel(row["authority_level"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_message_at=row["last_message_at"],
        )

    def _row_to_copilot_message(self, row: sqlite3.Row) -> CopilotMessage:
        return CopilotMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            role=row["role"],
            kind=row["kind"],
            text=row["text"],
            page=row["page"],
            symbol=row["symbol"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            client_message_id=row["client_message_id"],
            created_at=row["created_at"],
            payload=_loads(row["payload"]),
        )

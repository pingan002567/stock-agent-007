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

class MonitorRepoMixin:
    def save_monitor_rule(self, rule: MonitorRule) -> MonitorRule:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_rule(
                  rule_id, symbol, rule_type, severity, title, trigger_rule,
                  cooldown_seconds, enabled, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                  symbol=excluded.symbol,
                  rule_type=excluded.rule_type,
                  severity=excluded.severity,
                  title=excluded.title,
                  trigger_rule=excluded.trigger_rule,
                  cooldown_seconds=excluded.cooldown_seconds,
                  enabled=excluded.enabled,
                  payload=excluded.payload,
                  updated_at=excluded.updated_at
                """,
                (
                    rule.rule_id,
                    rule.symbol,
                    rule.rule_type,
                    rule.severity,
                    rule.title,
                    rule.trigger_rule,
                    rule.cooldown_seconds,
                    int(rule.enabled),
                    _json(rule),
                    rule.created_at,
                    rule.updated_at,
                ),
            )
            self.conn.commit()
        return rule

    def list_monitor_rules(self) -> List[MonitorRule]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM monitor_rule ORDER BY updated_at DESC, rule_id DESC"
            ).fetchall()
        return [MonitorRule(**_loads(row["payload"])) for row in rows]

    def delete_monitor_rule(self, rule_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM monitor_rule WHERE rule_id = ?", (rule_id,)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def save_monitor_event(self, event: EventContext) -> EventContext:
        evidence = event.evidence
        payload = event.payload or {}
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_event(
                  event_id, rule_id, rule_type, symbol, source, severity, title,
                  trigger_rule, dedupe_key, triggered_at, cooldown_until,
                  evidence_json, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                  rule_id=excluded.rule_id,
                  rule_type=excluded.rule_type,
                  symbol=excluded.symbol,
                  source=excluded.source,
                  severity=excluded.severity,
                  title=excluded.title,
                  trigger_rule=excluded.trigger_rule,
                  dedupe_key=excluded.dedupe_key,
                  triggered_at=excluded.triggered_at,
                  cooldown_until=excluded.cooldown_until,
                  evidence_json=excluded.evidence_json,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    event.event_id,
                    event.rule_id,
                    event.rule_type,
                    event.symbol,
                    event.source,
                    event.severity,
                    event.title,
                    event.trigger_rule,
                    event.dedupe_key,
                    event.triggered_at,
                    event.cooldown_until,
                    _json(evidence),
                    _json(event),
                    event.triggered_at,
                ),
            )
            self.conn.commit()
        return event

    def list_monitor_events(
        self,
        *,
        symbol: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> List[EventContext]:
        query = "SELECT * FROM monitor_event"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY triggered_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_monitor_event(row) for row in rows]

    def has_monitor_events(self) -> bool:
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM monitor_event LIMIT 1").fetchone()
        return row is not None

    def get_monitor_event(self, event_id: str) -> Optional[EventContext]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM monitor_event WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_monitor_event(row) if row else None

    def get_latest_monitor_event_by_dedupe_key(
        self, dedupe_key: str
    ) -> Optional[EventContext]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM monitor_event
                WHERE dedupe_key = ?
                ORDER BY triggered_at DESC, created_at DESC
                LIMIT 1
                """,
                (dedupe_key,),
            ).fetchone()
        return self._row_to_monitor_event(row) if row else None

    def save_monitor_status(self, status: MonitorStatus) -> MonitorStatus:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_status(status_key, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(status_key) DO UPDATE SET
                  payload=excluded.payload,
                  updated_at=excluded.updated_at
                """,
                ("default", _json(status), status.updated_at),
            )
            self.conn.commit()
        return status

    def get_monitor_status(self) -> Optional[MonitorStatus]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM monitor_status WHERE status_key = 'default'"
            ).fetchone()
        return MonitorStatus(**_loads(row["payload"])) if row else None

    def _row_to_monitor_event(self, row: sqlite3.Row) -> EventContext:
        payload = _loads(row["payload"])
        payload.setdefault("rule_id", row["rule_id"])
        payload.setdefault("rule_type", row["rule_type"])
        payload.setdefault("symbol", row["symbol"])
        payload.setdefault("source", row["source"])
        payload.setdefault("severity", row["severity"])
        payload.setdefault("title", row["title"])
        payload.setdefault("trigger_rule", row["trigger_rule"])
        payload.setdefault("dedupe_key", row["dedupe_key"])
        payload.setdefault("triggered_at", row["triggered_at"] or row["created_at"])
        payload.setdefault("cooldown_until", row["cooldown_until"])
        payload.setdefault("evidence", json.loads(row["evidence_json"] or "[]"))
        payload.setdefault("payload", payload.get("payload", {}))
        payload.setdefault("suggested_actions", payload.get("suggested_actions", []))
        return EventContext(**payload)

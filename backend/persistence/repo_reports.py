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

class ReportsRepoMixin:
    def save_report_template(self, template: ReportTemplate) -> ReportTemplate:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report_template(template_id, report_type, visible, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                  report_type=excluded.report_type,
                  visible=excluded.visible,
                  payload=excluded.payload,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at
                """,
                (
                    template.template_id,
                    template.report_type,
                    int(template.visible),
                    _json(template),
                    template.created_at,
                    template.updated_at,
                ),
            )
            self.conn.commit()
        return template

    def list_report_templates(
        self, *, visible_only: bool = True
    ) -> List[ReportTemplate]:
        query = "SELECT payload FROM report_template"
        params: list[Any] = []
        if visible_only:
            query += " WHERE visible = ?"
            params.append(1)
        query += " ORDER BY report_type ASC, created_at ASC, template_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [ReportTemplate(**_loads(row["payload"])) for row in rows]

    def get_report_template(self, template_id: str) -> Optional[ReportTemplate]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM report_template WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        return ReportTemplate(**_loads(row["payload"])) if row else None

    def save_report(self, report: Report) -> Report:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report(
                  report_id, report_type, source_type, source_id, symbol, quality_status,
                  latest_quality_check_id, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                  report_type=excluded.report_type,
                  source_type=excluded.source_type,
                  source_id=excluded.source_id,
                  symbol=excluded.symbol,
                  quality_status=excluded.quality_status,
                  latest_quality_check_id=excluded.latest_quality_check_id,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    report.report_id,
                    report.report_type,
                    report.source_type,
                    report.source_id,
                    report.symbol,
                    report.quality_status,
                    report.latest_quality_check_id,
                    _json(report),
                    report.created_at,
                ),
            )
            self.conn.commit()
        return report

    def list_reports(
        self,
        *,
        report_type: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> List[Report]:
        query = "SELECT payload FROM report"
        clauses: list[str] = []
        params: list[Any] = []
        if report_type is not None:
            clauses.append("report_type = ?")
            params.append(report_type)
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, report_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [Report(**_loads(row["payload"])) for row in rows]

    def get_report(self, report_id: str) -> Optional[Report]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM report WHERE report_id = ?", (report_id,)
            ).fetchone()
        return Report(**_loads(row["payload"])) if row else None

    def save_report_quality_check(
        self, check: ReportQualityCheck
    ) -> ReportQualityCheck:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report_quality_check(check_id, report_id, template_id, status, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    check.check_id,
                    check.report_id,
                    check.template_id,
                    check.status,
                    check.created_at,
                    _json(check),
                ),
            )
            self.conn.commit()
        return check

    def list_report_quality_checks(self, report_id: str) -> List[ReportQualityCheck]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT payload FROM report_quality_check
                WHERE report_id = ?
                ORDER BY created_at DESC, check_id DESC
                """,
                (report_id,),
            ).fetchall()
        return [ReportQualityCheck(**_loads(row["payload"])) for row in rows]

    def get_latest_report_quality_check(
        self, report_id: str
    ) -> Optional[ReportQualityCheck]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT payload FROM report_quality_check
                WHERE report_id = ?
                ORDER BY created_at DESC, check_id DESC
                LIMIT 1
                """,
                (report_id,),
            ).fetchone()
        return ReportQualityCheck(**_loads(row["payload"])) if row else None

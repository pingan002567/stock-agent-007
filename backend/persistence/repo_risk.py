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

class RiskRepoMixin:
    def save_risk_policy(self, policy: RiskPolicy) -> RiskPolicy:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO risk_policy(
                  policy_id, name, is_active, is_default, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                  name=excluded.name,
                  is_active=excluded.is_active,
                  is_default=excluded.is_default,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    policy.policy_id,
                    policy.name,
                    int(policy.is_active),
                    int(policy.is_default),
                    policy.created_at,
                    policy.updated_at,
                    _json(policy),
                ),
            )
            self.conn.commit()
        return policy

    def list_risk_policies(self) -> List[RiskPolicy]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM risk_policy ORDER BY is_active DESC, updated_at DESC, policy_id ASC"
            ).fetchall()
        return [RiskPolicy(**_loads(row["payload"])) for row in rows]

    def get_risk_policy(self, policy_id: str) -> Optional[RiskPolicy]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM risk_policy WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        return RiskPolicy(**_loads(row["payload"])) if row else None

    def get_active_risk_policy(self) -> Optional[RiskPolicy]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT payload FROM risk_policy
                WHERE is_active = 1 OR is_default = 1
                ORDER BY is_active DESC, is_default DESC, updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        return RiskPolicy(**_loads(row["payload"])) if row else None

    def activate_risk_policy(
        self, policy_id: str, updated_at: str | None = None
    ) -> Optional[RiskPolicy]:
        with self._lock:
            activated: RiskPolicy | None = None
            target_updated_at = updated_at or now_iso()
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                row = self.conn.execute(
                    "SELECT payload FROM risk_policy WHERE policy_id = ?", (policy_id,)
                ).fetchone()
                if not row:
                    return None
                policy = RiskPolicy(**_loads(row["payload"]))
                self.conn.execute(
                    "UPDATE risk_policy SET is_active = 0, is_default = 0 WHERE policy_id <> ?",
                    (policy_id,),
                )
                other_rows = self.conn.execute(
                    "SELECT policy_id, payload FROM risk_policy WHERE policy_id <> ?",
                    (policy_id,),
                ).fetchall()
                for other_row in other_rows:
                    other = RiskPolicy(**_loads(other_row["payload"]))
                    cleared = other.model_copy(
                        update={"is_active": False, "is_default": False}
                    )
                    self.conn.execute(
                        "UPDATE risk_policy SET payload = ? WHERE policy_id = ?",
                        (_json(cleared), cleared.policy_id),
                    )
                activated = policy.model_copy(
                    update={
                        "is_active": True,
                        "is_default": True,
                        "updated_at": target_updated_at,
                    }
                )
                self.conn.execute(
                    """
                    UPDATE risk_policy
                    SET name = ?, is_active = 1, is_default = 1, created_at = ?, updated_at = ?, payload = ?
                    WHERE policy_id = ?
                    """,
                    (
                        activated.name,
                        activated.created_at,
                        activated.updated_at,
                        _json(activated),
                        activated.policy_id,
                    ),
                )
        return activated

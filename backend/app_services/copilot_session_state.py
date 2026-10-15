"""In-memory per-session conversational state for the Copilot.

Extracted from copilot_service.py. Holds the rolling turn summary and the
active draft/review tracking that feeds multi-turn context back to the agent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 内存中保留的会话轮次记忆数量上限（LRU 淘汰），防止单进程长跑无限增长。
MAX_SESSION_STATES = 256


@dataclass
class TurnSummary:
    question: str
    intent: str
    outcome: str
    summary: str
    state_changes: dict[str, Any]
    error_hint: str | None = None

    def to_context(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "summary": self.summary,
            "state_changes": self.state_changes,
        }

    @property
    def is_empty(self) -> bool:
        return not self.summary and not self.state_changes.get("generated_drafts") \
               and not self.state_changes.get("confirmed_drafts")


@dataclass
class SessionStateData:
    active_drafts: dict[str, dict[str, Any]]
    active_reviews: dict[str, dict[str, Any]]
    total_runs: int = 0

    def apply_turn(self, turn: TurnSummary) -> None:
        import datetime as _dt
        now = _dt.datetime.now().isoformat()
        for d in turn.state_changes.get("generated_drafts", []):
            self.active_drafts[d["id"]] = {"symbol": d["symbol"], "status": "pending", "created_at": now}
        for d in turn.state_changes.get("confirmed_drafts", []):
            if d["id"] in self.active_drafts:
                self.active_drafts[d["id"]]["status"] = "confirmed"
        for r in turn.state_changes.get("created_reviews", []):
            self.active_reviews[r["id"]] = {"draft_id": r.get("draft_id"), "status": "created", "created_at": now}
        self.total_runs += 1

    def to_context(self) -> dict[str, Any]:
        pending = {k: v for k, v in self.active_drafts.items() if v["status"] == "pending"}
        confirmed = {k: v for k, v in self.active_drafts.items() if v["status"] == "confirmed"}
        actions = []
        for d_id, d in pending.items():
            actions.append(f"草案 {d_id}({d['symbol']}) 待确认")
        for d_id, d in confirmed.items():
            actions.append(f"草案 {d_id} 可创建交易前审查")
        return {
            "pending_drafts": [{"id": k, "symbol": v["symbol"]} for k, v in pending.items()],
            "confirmed_drafts": [{"id": k, "symbol": v["symbol"]} for k, v in confirmed.items()],
            "active_reviews": [{"id": k, **v} for k, v in self.active_reviews.items()],
            "pending_actions": actions,
            "total_runs": self.total_runs,
        }

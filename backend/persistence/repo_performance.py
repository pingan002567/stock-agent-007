"""组合每日净值快照：回撤需要历史序列，而持仓表只保留"当前状态"。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.schemas import now_iso


class PerformanceRepoMixin:
    def upsert_nav_snapshot(self, day: str, nav: float, market_value: float, cash: float) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO portfolio_nav_daily(day, nav, market_value, cash, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                  nav=excluded.nav, market_value=excluded.market_value,
                  cash=excluded.cash, created_at=excluded.created_at
                """,
                (str(day), round(float(nav), 2), round(float(market_value), 2),
                 round(float(cash), 2), now_iso()),
            )
            self.conn.commit()

    def get_nav_snapshot(self, day: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM portfolio_nav_daily WHERE day = ?", (str(day),)
        ).fetchone()
        return dict(row) if row else None

    def list_nav_snapshots(self, limit: int = 250) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM portfolio_nav_daily ORDER BY day DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def peak_nav(self) -> Optional[float]:
        row = self.conn.execute("SELECT MAX(nav) AS peak FROM portfolio_nav_daily").fetchone()
        peak = row["peak"] if row else None
        return None if peak is None else round(float(peak), 2)

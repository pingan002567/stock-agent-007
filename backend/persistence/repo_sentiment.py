"""市场情绪日快照：把每天收盘后的情绪温度落库，支撑「处在周期哪个位置」。"""

from __future__ import annotations

from typing import Any, Optional


class SentimentRepoMixin:
    def record_market_sentiment(self, snapshot: dict[str, Any]) -> None:
        """按 trade_date 幂等 upsert 一条情绪快照。

        只在温度分可计算时写入；否则不落库（0 分会被误读成冰点）。
        """
        temperature = snapshot.get("temperature")
        if temperature is None:
            return
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO market_sentiment_daily (
                  trade_date, temperature, phase, limit_up, max_streak,
                  broken_rate, red_ratio, rising, falling, divergence, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                  temperature=excluded.temperature,
                  phase=excluded.phase,
                  limit_up=excluded.limit_up,
                  max_streak=excluded.max_streak,
                  broken_rate=excluded.broken_rate,
                  red_ratio=excluded.red_ratio,
                  rising=excluded.rising,
                  falling=excluded.falling,
                  divergence=excluded.divergence,
                  recorded_at=excluded.recorded_at
                """,
                (
                    snapshot["as_of"],
                    temperature,
                    snapshot.get("phase"),
                    snapshot.get("limit_up", {}).get("count"),
                    snapshot.get("limit_up", {}).get("max_streak"),
                    (snapshot.get("broken") or {}).get("rate"),
                    (snapshot.get("previous_limit_up") or {}).get("red_ratio"),
                    (snapshot.get("breadth") or {}).get("rising"),
                    (snapshot.get("breadth") or {}).get("falling"),
                    snapshot.get("divergence"),
                    snapshot.get("recorded_at"),
                ),
            )
            self.conn.commit()

    def list_market_sentiment(self, limit: int = 60) -> list[dict[str, Any]]:
        """最近的日快照，按交易日升序（画曲线用）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM market_sentiment_daily ORDER BY trade_date DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def phase_streak(self, phase: Optional[str]) -> int:
        """当前阶段已经连续多少天（升温第几天 / 退潮第几天）。"""
        if not phase:
            return 0
        with self._lock:
            rows = self.conn.execute(
                "SELECT phase FROM market_sentiment_daily ORDER BY trade_date DESC LIMIT 60"
            ).fetchall()
        streak = 0
        for row in rows:
            if row["phase"] == phase:
                streak += 1
            elif streak == 0 and row["phase"] is None:
                continue
            else:
                break
        return streak

"""情绪日快照落库的纯逻辑测试（内存 sqlite，不联网）。"""

from __future__ import annotations

from backend.persistence.db import connect
from backend.persistence.repositories import WorkbenchRepository


def _repo(tmp_path):
    repo = WorkbenchRepository(connect(tmp_path / "t.sqlite3"))
    return repo


def test_record_is_idempotent_and_streak(tmp_path) -> None:
    repo = _repo(tmp_path)
    snap = {
        "as_of": "2026-10-21",
        "temperature": 55.0,
        "phase": "分化",
        "limit_up": {"count": 50, "max_streak": 4},
        "broken": {"rate": 0.275},
        "previous_limit_up": {"red_ratio": 0.72},
        "breadth": {"rising": 1100, "falling": 4351},
        "divergence": "结构性分化",
    }
    repo.record_market_sentiment(snap)
    repo.record_market_sentiment(snap)  # 幂等：同一天覆盖
    rows = repo.list_market_sentiment()
    assert len(rows) == 1
    assert rows[0]["trade_date"] == "2026-10-21"
    assert rows[0]["phase"] == "分化"
    assert repo.phase_streak("分化") == 1


def test_phase_streak_counts_consecutive_days(tmp_path) -> None:
    repo = _repo(tmp_path)
    for i, (d, ph) in enumerate(
        [("2026-10-23", "升温"), ("2026-10-22", "升温"), ("2026-10-21", "升温"), ("2026-10-20", "分化")]
    ):
        repo.record_market_sentiment(
            {"as_of": d, "temperature": 66.0, "phase": ph, "limit_up": {}, "broken": {}, "previous_limit_up": {}, "breadth": {}}
        )
    assert repo.phase_streak("升温") == 3
    assert repo.phase_streak("分化") == 0  # 已不是最近阶段


def test_no_temperature_is_not_recorded(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.record_market_sentiment({"as_of": "2026-10-21", "temperature": None})
    assert repo.list_market_sentiment() == []

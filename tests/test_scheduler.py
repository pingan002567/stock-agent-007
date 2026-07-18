"""定时任务:日程计算与 API 回路(stub 运行时)。"""
from __future__ import annotations

from datetime import datetime

from backend.app_services.scheduler_service import compute_next_run


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def test_compute_next_run_daily():
    # 未到点 → 当天;已过点 → 明天
    assert compute_next_run("daily@08:30", _dt("2026-07-19T07:00")) == _dt("2026-07-19T08:30")
    assert compute_next_run("daily@08:30", _dt("2026-07-19T09:00")) == _dt("2026-07-20T08:30")
    # 恰好在点上 → 下一天(严格大于)
    assert compute_next_run("daily@08:30", _dt("2026-07-19T08:30")) == _dt("2026-07-20T08:30")


def test_compute_next_run_weekly():
    # 2026-07-19 是周日(ISO 7)
    assert compute_next_run("weekly@7@17:00", _dt("2026-07-19T09:00")) == _dt("2026-07-19T17:00")
    assert compute_next_run("weekly@7@17:00", _dt("2026-07-19T18:00")) == _dt("2026-07-26T17:00")
    assert compute_next_run("weekly@1@09:00", _dt("2026-07-19T09:00")) == _dt("2026-07-20T09:00")


def test_compute_next_run_every_and_invalid():
    assert compute_next_run("every@30m", _dt("2026-07-19T09:00")) == _dt("2026-07-19T09:30")
    assert compute_next_run("every@1m", _dt("2026-07-19T09:00")) is None  # 下限 5 分钟
    for bad in ("", "cron@* * *", "daily@25:00", "weekly@8@10:00", "hourly@10"):
        assert compute_next_run(bad, _dt("2026-07-19T09:00")) is None, bad


def test_scheduled_tasks_api_roundtrip(tmp_path, monkeypatch):
    from tests.test_api import make_client

    client = make_client(tmp_path)

    # 默认种子任务可见,含 next_run_at 派生字段
    listed = client.get("/api/scheduled-tasks").json()["items"]
    names = {t["task_id"] for t in listed}
    assert {"sched_premarket", "sched_weekly_review"} <= names
    premarket = next(t for t in listed if t["task_id"] == "sched_premarket")
    assert premarket["enabled"] is True and premarket["next_run_at"]

    # 新建 + 校验非法日程被拒
    created = client.post("/api/scheduled-tasks", json={
        "name": "收盘复评", "prompt": "复评今日持仓表现", "schedule": "daily@15:30",
    })
    assert created.status_code == 200
    task_id = created.json()["task_id"]
    assert client.post("/api/scheduled-tasks", json={
        "name": "bad", "prompt": "x", "schedule": "cron@*",
    }).status_code == 400

    # 停用 → next_run_at 置空;立即运行(stub 快速收口)回写痕迹
    toggled = client.post(f"/api/scheduled-tasks/{task_id}/toggle", json={"enabled": False}).json()
    assert toggled["enabled"] is False
    listed = client.get("/api/scheduled-tasks").json()["items"]
    assert next(t for t in listed if t["task_id"] == task_id)["next_run_at"] is None

    ran = client.post(f"/api/scheduled-tasks/{task_id}/run-now").json()
    assert ran["status"] == "completed" and ran["run_id"]
    listed = client.get("/api/scheduled-tasks").json()["items"]
    rec = next(t for t in listed if t["task_id"] == task_id)
    assert rec["last_status"] == "completed" and rec["last_run_at"]

    # 删除
    assert client.delete(f"/api/scheduled-tasks/{task_id}").json()["ok"] is True
    listed = client.get("/api/scheduled-tasks").json()["items"]
    assert all(t["task_id"] != task_id for t in listed)

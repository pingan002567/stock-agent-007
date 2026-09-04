"""定时任务:日程计算与 API 回路(stub 运行时)。"""
from __future__ import annotations

from datetime import datetime

import asyncio

from backend.app_services.scheduler_service import (
    cap_duty_authority,
    compute_next_run,
    infer_ops_session,
    next_duty_run,
    skip_reason_for,
    uses_cn_session_calendar,
)
from backend.schemas import AuthorityLevel


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def test_infer_ops_session_and_cap_duty_authority():
    assert infer_ops_session({"task_id": "sched_premarket", "name": "盘前简报"}) == "premarket"
    assert infer_ops_session({"task_id": "x", "name": "收盘复评"}) == "close"
    assert infer_ops_session({"task_id": "sched_weekly_review", "name": "周度复盘"}) == "weekly"
    assert cap_duty_authority("A5") == AuthorityLevel.A3
    assert cap_duty_authority("A2") == AuthorityLevel.A3
    assert cap_duty_authority("nope") == AuthorityLevel.A3
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
    assert {"sched_premarket", "sched_close", "sched_weekly_review"} <= names
    premarket = next(t for t in listed if t["task_id"] == "sched_premarket")
    close = next(t for t in listed if t["task_id"] == "sched_close")
    weekly = next(t for t in listed if t["task_id"] == "sched_weekly_review")
    assert premarket["enabled"] is True and premarket["next_run_at"]
    assert close["enabled"] is True and close["schedule"] == "daily@15:15"
    assert weekly["enabled"] is False

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
    assert ran.get("report_id")
    listed = client.get("/api/scheduled-tasks").json()["items"]
    rec = next(t for t in listed if t["task_id"] == task_id)
    assert rec["last_status"] == "completed" and rec["last_run_at"]
    assert rec.get("last_report_id") == ran["report_id"]

    reports = client.get("/api/reports").json()["items"]
    assert any(item["report_type"] == "ops_briefing" and item["report_id"] == ran["report_id"] for item in reports)
    overview = client.get("/api/overview").json()
    assert overview["latest_ops_briefing"]["report_id"] == ran["report_id"]
    assert overview["latest_ops_briefing"]["auto_trade"] is False
    assert "inbox_summary" in overview

    # 删除
    assert client.delete(f"/api/scheduled-tasks/{task_id}").json()["ok"] is True
    listed = client.get("/api/scheduled-tasks").json()["items"]
    assert all(t["task_id"] != task_id for t in listed)


def test_failed_scheduled_task_still_persists_briefing_and_inbox_item(tmp_path, monkeypatch):
    from tests.test_api import make_client

    client = make_client(tmp_path)
    services = client.app.state.services

    def boom(*_args, **_kwargs):
        raise RuntimeError("forced scheduler failure")

    pushed: list[tuple[str, str]] = []
    services.scheduler_service.alert_sink = lambda title, text: pushed.append((title, text))
    monkeypatch.setattr(services.copilot_service, "create_run", boom)
    ran = client.post("/api/scheduled-tasks/sched_premarket/run-now").json()
    assert ran["status"] == "failed"
    assert ran.get("report_id")
    inbox = client.get("/api/review-inbox").json()["items"]
    assert any(item["item_type"] == "scheduled_task_failed" for item in inbox)
    overview = client.get("/api/overview").json()
    assert overview["latest_ops_briefing"]["report_id"] == ran["report_id"]
    assert overview["inbox_summary"]["high_count"] >= 1
    assert pushed and pushed[0][0].startswith("值班失败")


def test_uses_cn_session_calendar_only_for_duty_or_explicit_cn():
    assert uses_cn_session_calendar({"task_id": "sched_premarket"}) is True
    assert uses_cn_session_calendar({"task_id": "sched_close", "calendar": "CN"}) is True
    assert uses_cn_session_calendar({"task_id": "sched_weekly_review"}) is False
    assert uses_cn_session_calendar({"task_id": "custom", "name": "收盘复评"}) is False
    assert uses_cn_session_calendar({"task_id": "custom", "calendar": "CN"}) is True


def test_next_duty_run_skips_weekend_and_cn_holiday(monkeypatch):
    from datetime import date

    holidays = {
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
        date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
        date(2026, 10, 7), date(2026, 10, 8),
    }

    def fake_is_trading_day(market, day=None):
        if day is None:
            day = date.today()
        if day.weekday() >= 5:
            return False
        if market == "CN":
            return day not in holidays
        return True

    monkeypatch.setattr("backend.stock_domain.trading_calendar.is_trading_day", fake_is_trading_day)
    close = {"task_id": "sched_close", "calendar": "CN", "schedule": "daily@15:15", "name": "收盘体检"}
    weekly = {"task_id": "sched_weekly_review", "schedule": "weekly@7@17:00", "name": "周度复盘"}

    # 周五收盘后 → 跳过周末，落到下周一
    assert next_duty_run(close, _dt("2026-07-17T16:00")) == _dt("2026-07-20T15:15")
    # 国庆前一晚 → 跳过 10/1–10/8，落到 10/9
    assert next_duty_run(close, _dt("2026-09-30T16:00")) == _dt("2026-10-09T15:15")
    # 周度周日不跟 A 股休市
    assert next_duty_run(weekly, _dt("2026-10-03T10:00")) == _dt("2026-10-04T17:00")

    assert skip_reason_for(close, _dt("2026-07-18T10:00")) == "休市"  # 周六
    assert skip_reason_for(close, _dt("2026-10-01T10:00")) == "休市"
    assert skip_reason_for(close, _dt("2026-07-20T10:00")) is None
    assert skip_reason_for(weekly, _dt("2026-10-04T10:00")) is None


def test_honor_calendar_skip_does_not_persist_briefing(tmp_path, monkeypatch):
    from tests.test_api import make_client

    client = make_client(tmp_path)
    services = client.app.state.services
    monkeypatch.setattr(
        "backend.app_services.scheduler_service.skip_reason_for",
        lambda task, now=None: "休市",
    )
    task = next(t for t in services.scheduler_service.list_tasks() if t["task_id"] == "sched_close")
    outcome = asyncio.run(services.scheduler_service._execute(task, honor_calendar=True))
    assert outcome["status"] == "skipped"
    assert outcome["report_id"] is None
    reports = client.get("/api/reports").json()["items"]
    assert not any(item.get("report_type") == "ops_briefing" for item in reports)
    listed = client.get("/api/scheduled-tasks").json()["items"]
    rec = next(t for t in listed if t["task_id"] == "sched_close")
    assert rec["last_status"] == "skipped"
    assert rec.get("skip_reason") == "休市"


def test_sched_close_injected_when_missing_from_existing_config(tmp_path):
    from tests.test_api import make_client

    client = make_client(tmp_path)
    services = client.app.state.services
    services.repo.set_config(
        "scheduled_tasks",
        {"items": [{"task_id": "sched_premarket", "name": "盘前简报", "prompt": "x",
                    "schedule": "daily@08:30", "enabled": True, "page": "chat",
                    "authority_level": "A3"}]},
    )
    listed = services.scheduler_service.list_tasks()
    assert any(item["task_id"] == "sched_close" for item in listed)
    assert any(item["task_id"] == "sched_premarket" for item in listed)

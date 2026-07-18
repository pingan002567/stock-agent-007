"""定时任务:按日程自动发起 Copilot run(盘前简报/周度复盘等)。

DeerFlow harness 无 scheduler(Gateway 专属,见 doc/DEERFLOW_21_RESEARCH.md P1),
自建轻量 cron:任务存 repo config(单用户,量小),asyncio 循环沿用
monitor_service 模式,到点即 create_run 并 drain 流至收口。

日程表达(刻意不引 croniter,三种够用):
  ``daily@HH:MM``      每天,本机时区
  ``weekly@N@HH:MM``   每周,N=1..7(ISO,1=周一 7=周日)
  ``every@Nm``         每 N 分钟(N>=5)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from backend.schemas import AuthorityLevel, CopilotRequest, now_iso

logger = logging.getLogger("scheduler")

CONFIG_KEY = "scheduled_tasks"
CHECK_INTERVAL_SECONDS = 30
RUN_TIMEOUT_SECONDS = 900

DEFAULT_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "sched_premarket",
        "name": "盘前简报",
        "prompt": "生成今日盘前简报:汇总自选与持仓相关的隔夜要闻与情报,列出今天需要重点关注的标的和风险点。",
        "page": "chat",
        "authority_level": "A2",
        "schedule": "daily@08:30",
        "enabled": True,
    },
    {
        "task_id": "sched_weekly_review",
        "name": "周度复盘",
        "prompt": "生成本周组合复盘报告:本周持仓表现、盯盘事件回顾、风险状况变化与下周关注点。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "weekly@7@17:00",
        "enabled": False,
    },
]


def compute_next_run(schedule: str, after: datetime) -> Optional[datetime]:
    """日程 → after 之后最近一次触发时刻;非法日程返回 None。"""
    try:
        kind, _, rest = schedule.partition("@")
        if kind == "daily":
            hh, mm = (int(x) for x in rest.split(":"))
            candidate = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate <= after:
                candidate += timedelta(days=1)
            return candidate
        if kind == "weekly":
            day_s, _, time_s = rest.partition("@")
            day = int(day_s)  # ISO 1..7
            hh, mm = (int(x) for x in time_s.split(":"))
            if not 1 <= day <= 7:
                return None
            candidate = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta_days = (day - candidate.isoweekday()) % 7
            candidate += timedelta(days=delta_days)
            if candidate <= after:
                candidate += timedelta(days=7)
            return candidate
        if kind == "every":
            minutes = int(rest.rstrip("m"))
            if minutes < 5:
                return None
            return after + timedelta(minutes=minutes)
    except (ValueError, AttributeError):
        return None
    return None


class SchedulerService:
    def __init__(self, *, repo, copilot_service, audit_service) -> None:
        self.repo = repo
        self.copilot_service = copilot_service
        self.audit_service = audit_service
        self._loop_task: asyncio.Task | None = None

    # ── 存取(repo config 单键,属主唯一) ──

    def list_tasks(self) -> list[dict[str, Any]]:
        data = self.repo.get_config(CONFIG_KEY, {"items": DEFAULT_TASKS})
        items = list(data.get("items") or [])
        now = datetime.now()
        for item in items:
            nxt = compute_next_run(str(item.get("schedule") or ""), now)
            item["next_run_at"] = nxt.isoformat(timespec="minutes") if (nxt and item.get("enabled")) else None
        return items

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.repo.set_config(CONFIG_KEY, {"items": items})

    def upsert_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule = str(payload.get("schedule") or "")
        if compute_next_run(schedule, datetime.now()) is None:
            raise ValueError(f"invalid schedule: {schedule!r} (daily@HH:MM / weekly@N@HH:MM / every@Nm)")
        items = self.list_tasks()
        task_id = str(payload.get("task_id") or f"sched_{uuid4().hex[:8]}")
        existing = next((t for t in items if t["task_id"] == task_id), None)
        record = {
            "task_id": task_id,
            "name": str(payload.get("name") or "未命名任务"),
            "prompt": str(payload.get("prompt") or ""),
            "page": str(payload.get("page") or "chat"),
            "authority_level": str(payload.get("authority_level") or "A2"),
            "schedule": schedule,
            "enabled": bool(payload.get("enabled", True)),
            "last_run_at": (existing or {}).get("last_run_at"),
            "last_status": (existing or {}).get("last_status"),
        }
        if existing:
            items[items.index(existing)] = record
        else:
            items.append(record)
        self._save(items)
        self.audit_service.record("scheduled task upserted", f"{task_id} {schedule}")
        return record

    def set_enabled(self, task_id: str, enabled: bool) -> dict[str, Any]:
        items = self.list_tasks()
        task = next((t for t in items if t["task_id"] == task_id), None)
        if task is None:
            raise KeyError(task_id)
        task["enabled"] = bool(enabled)
        self._save(items)
        return task

    def delete_task(self, task_id: str) -> None:
        items = [t for t in self.list_tasks() if t["task_id"] != task_id]
        self._save(items)

    # ── 执行 ──

    async def run_task_now(self, task_id: str) -> dict[str, Any]:
        items = self.list_tasks()
        task = next((t for t in items if t["task_id"] == task_id), None)
        if task is None:
            raise KeyError(task_id)
        return await self._execute(task)

    async def _execute(self, task: dict[str, Any]) -> dict[str, Any]:
        stamp = datetime.now().strftime("%m-%d %H:%M")
        request = CopilotRequest(
            message=f"[定时任务·{task['name']} {stamp}] {task['prompt']}",
            page=task.get("page") or "chat",
            authority_level=AuthorityLevel(task.get("authority_level") or "A2"),
        )
        outcome = {"run_id": None, "status": "failed", "error": None}
        try:
            run = self.copilot_service.create_run(request)
            outcome["run_id"] = run.run_id

            async def _drain() -> None:
                async for event in self.copilot_service.stream_run(run.run_id, run.task_id):
                    if event.type == "error":
                        outcome["error"] = str(event.payload.get("error") or "run error")

            await asyncio.wait_for(_drain(), timeout=RUN_TIMEOUT_SECONDS)
            outcome["status"] = "completed" if not outcome["error"] else "failed"
        except asyncio.TimeoutError:
            outcome["error"] = f"timeout after {RUN_TIMEOUT_SECONDS}s"
        except Exception as exc:  # 单任务失败不拖垮循环
            outcome["error"] = str(exc)[:200]
        # 回写执行痕迹(重读避免覆盖并发修改)
        items = self.list_tasks()
        task_rec = next((t for t in items if t["task_id"] == task["task_id"]), None)
        if task_rec is not None:
            task_rec["last_run_at"] = now_iso()
            task_rec["last_status"] = outcome["status"]
            task_rec["last_run_id"] = outcome["run_id"]
            task_rec["last_error"] = outcome["error"]
            self._save(items)
        self.audit_service.record(
            "scheduled task executed",
            f"{task['task_id']} -> {outcome['status']}"
            + (f" ({outcome['error']})" if outcome["error"] else ""),
        )
        return outcome

    # ── 循环(monitor_service 同款生命周期) ──

    async def startup(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._run_loop(), name="workbench-scheduler-loop")

    async def shutdown(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        # due 判定用「上次检查时刻 < 触发点 <= 现在」窗口,重启错过的触发不补跑
        last_check = datetime.now()
        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                now = datetime.now()
                for task in self.list_tasks():
                    if not task.get("enabled"):
                        continue
                    nxt = compute_next_run(str(task.get("schedule") or ""), last_check)
                    if nxt and last_check < nxt <= now:
                        logger.info("scheduled task due: %s", task["task_id"])
                        await self._execute(task)
                last_check = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler loop iteration failed")
                last_check = datetime.now()

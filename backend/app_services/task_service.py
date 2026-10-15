from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import AgentTask


class TaskService:
    def __init__(self, repo: WorkbenchRepository) -> None:
        self.repo = repo

    def create(
        self,
        title: str,
        source: str,
        current_step: str,
        run_id: str | None = None,
        skill_trace: list[dict[str, Any]] | None = None,
    ) -> AgentTask:
        task = AgentTask(
            task_id=f"task_{uuid4().hex[:10]}",
            title=title,
            source=source,
            progress=5,
            status="running",
            current_step=current_step,
            run_id=run_id,
            skill_trace=skill_trace or [],
        )
        return self.repo.save_task(task)

    def update(self, task_id: str, *, status: str | None = None, progress: int | None = None, current_step: str | None = None) -> AgentTask:
        task = self.repo.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = progress
        if current_step is not None:
            task.current_step = current_step
        return self.repo.save_task(task)

    def retry(self, task_id: str) -> AgentTask:
        task = self.repo.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        task.status = "running"
        task.progress = max(task.progress, 8)
        task.current_step = "retrying"
        return self.repo.save_task(task)

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import ToolExecution


class ToolExecutionService:
    def __init__(self, repo: WorkbenchRepository, summary_limit: int = 240) -> None:
        self.repo = repo
        self.summary_limit = summary_limit

    def record(
        self,
        *,
        tool: str,
        domain: str,
        status: str,
        authority_level: str,
        arguments: dict[str, Any] | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        call_id: str | None = None,
        source_mode: str | None = None,
        evidence_refs: list[str] | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> ToolExecution:
        execution = ToolExecution(
            execution_id=f"exec_{uuid4().hex[:12]}",
            tool=tool,
            domain=domain,
            status=status,
            authority_level=authority_level,
            arguments=arguments or {},
            task_id=task_id,
            run_id=run_id,
            call_id=call_id,
            source_mode=source_mode or "unknown",
            evidence_refs=evidence_refs or [],
            result_summary=self._truncate_summary(self._summarize(result)),
            error=error,
        )
        return self.repo.save_tool_execution(execution)

    def _summarize(self, value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        elif hasattr(value, "dict"):
            value = value.dict()
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _truncate_summary(self, summary: str) -> str:
        if len(summary) <= self.summary_limit:
            return summary
        return summary[: self.summary_limit - 1] + "…"

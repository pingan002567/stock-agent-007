from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from threading import RLock
from typing import Optional
from uuid import uuid4

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    CopilotRunLog,
    ProviderCallLog,
    RuntimeMetricSnapshot,
    now_iso,
)


@dataclass
class RuntimeObserver:
    repo: WorkbenchRepository | None = None

    def __post_init__(self) -> None:
        self._lock = RLock()

    def configure(self, repo: WorkbenchRepository) -> None:
        with self._lock:
            self.repo = repo

    def record_provider_call(
        self,
        *,
        capability: str,
        market: str | None,
        symbol: str | None,
        provider: str,
        fallback_provider: str,
        status: str,
        degraded_reason: str | None,
        duration_ms: float,
        payload: dict | None = None,
    ) -> None:
        if not self.repo:
            return
        self.repo.save_provider_call_log(
            ProviderCallLog(
                call_id=f"provider_call_{uuid4().hex[:12]}",
                capability=capability,
                market=market,
                symbol=symbol,
                provider=provider,
                fallback_provider=fallback_provider,
                status=status,
                degraded_reason=degraded_reason,
                duration_ms=duration_ms,
                payload=payload or {},
            )
        )

    def save_copilot_run_log(self, log: CopilotRunLog) -> CopilotRunLog:
        if not self.repo:
            return log
        return self.repo.save_copilot_run_log(log)

    def list_provider_events(
        self, *, limit: int = 100, capability: str | None = None
    ) -> list[ProviderCallLog]:
        if not self.repo:
            return []
        return self.repo.list_provider_call_logs(limit=limit, capability=capability)

    def daily_cost_summary(self) -> dict[str, Any]:
        """Aggregate token usage & cost per day per model.

        Returns a dict with:
          - days: [{date, total_cost, total_input_tokens, total_output_tokens, run_count, models: [...]}]
          - total: {total_cost, total_input_tokens, total_output_tokens, total_runs, models: {model: cost}}
        """
        runs = self.list_copilot_runs(limit=2000)
        from collections import defaultdict
        by_day: dict[str, dict] = defaultdict(lambda: {
            "total_cost": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
            "run_count": 0, "models": defaultdict(lambda: {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "run_count": 0}),
        })
        totals = {"total_cost": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
                   "total_runs": 0, "models": defaultdict(lambda: {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "run_count": 0})}
        for run in runs:
            if run.status not in ("completed",):
                continue
            day = run.created_at[:10]
            model = run.model_name or "unknown"
            cost = run.cost or 0.0
            inp = run.usage_input_tokens or 0
            out = run.usage_output_tokens or 0
            d = by_day[day]
            d["total_cost"] += cost
            d["total_input_tokens"] += inp
            d["total_output_tokens"] += out
            d["run_count"] += 1
            dm = d["models"][model]
            dm["cost"] += cost
            dm["input_tokens"] += inp
            dm["output_tokens"] += out
            dm["run_count"] += 1
            totals["total_cost"] += cost
            totals["total_input_tokens"] += inp
            totals["total_output_tokens"] += out
            totals["total_runs"] += 1
            tm = totals["models"][model]
            tm["cost"] += cost
            tm["input_tokens"] += inp
            tm["output_tokens"] += out
            tm["run_count"] += 1
        days_list = []
        for day_key in sorted(by_day.keys(), reverse=True):
            d = dict(by_day[day_key])
            d["date"] = day_key
            d["models"] = {k: dict(v) for k, v in d["models"].items()}
            d["total_cost"] = round(d["total_cost"], 6)
            days_list.append(d)
        totals["models"] = {k: dict(v) for k, v in totals["models"].items()}
        totals["total_cost"] = round(totals["total_cost"], 6)
        return {"days": days_list, "total": dict(totals)}

    def list_copilot_runs(
        self, *, limit: int = 100, status: str | None = None
    ) -> list[CopilotRunLog]:
        if not self.repo:
            return []
        return self.repo.list_copilot_run_logs(limit=limit, status=status)

    def get_copilot_run_log(self, run_id: str) -> CopilotRunLog | None:
        if not self.repo:
            return None
        return self.repo.get_copilot_run_log(run_id)

    def snapshot_metrics(self) -> RuntimeMetricSnapshot:
        provider_events = self.list_provider_events(limit=500)
        copilot_runs = self.list_copilot_runs(limit=500)
        provider_failures = [
            item for item in provider_events if item.status != "succeeded"
        ]
        provider_durations = [item.duration_ms for item in provider_events]
        copilot_failures = [
            item for item in copilot_runs if item.status not in {"completed", "running"}
        ]
        usage_input = sum(item.usage_input_tokens or 0 for item in copilot_runs)
        usage_output = sum(item.usage_output_tokens or 0 for item in copilot_runs)
        copilot_costs = [item.cost for item in copilot_runs if item.cost is not None]
        copilot_latencies = [
            item.latency_ms for item in copilot_runs if item.latency_ms is not None
        ]
        error_dist: dict[str, int] = {}
        for item in copilot_runs:
            if item.error_category:
                error_dist[item.error_category] = error_dist.get(item.error_category, 0) + 1
        # Per-provider breakdown
        provider_stats: dict[str, dict] = {}
        for item in provider_events:
            prov = item.provider or "unknown"
            if prov not in provider_stats:
                provider_stats[prov] = {
                    "total_calls": 0,
                    "failure_count": 0,
                    "fallback_count": 0,
                    "secondary_count": 0,
                    "avg_duration_ms": 0.0,
                    "durations": [],
                }
            provider_stats[prov]["total_calls"] += 1
            provider_stats[prov]["durations"].append(item.duration_ms)
            if item.status in ("fallback", "failed", "circuit_open"):
                provider_stats[prov]["fallback_count"] += 1
                provider_stats[prov]["failure_count"] += 1
            elif item.status == "secondary":
                provider_stats[prov]["secondary_count"] += 1
        for prov, stats in provider_stats.items():
            dur_list = stats.pop("durations")
            stats["avg_duration_ms"] = round(mean(dur_list), 2) if dur_list else 0.0
        payload = {
            "provider": {
                "total_calls": len(provider_events),
                "failure_count": len(provider_failures),
                "fallback_count": len(
                    [item for item in provider_events if item.status == "fallback"]
                ),
                "secondary_rescue_count": len(
                    [item for item in provider_events if item.status == "secondary"]
                ),
                "avg_duration_ms": round(mean(provider_durations), 2)
                if provider_durations
                else 0.0,
                "last_degraded_reason": next(
                    (
                        item.degraded_reason
                        for item in provider_failures
                        if item.degraded_reason
                    ),
                    None,
                ),
                "per_provider": provider_stats,
            },
            "copilot": {
                "total_runs": len(copilot_runs),
                "failure_count": len(copilot_failures),
                "avg_tool_calls": round(
                    mean([item.tool_call_count for item in copilot_runs]), 2
                )
                if copilot_runs
                else 0.0,
                "usage_input_tokens": usage_input,
                "usage_output_tokens": usage_output,
                "total_cost": round(sum(copilot_costs), 6) if copilot_costs else 0.0,
                "avg_cost": round(mean(copilot_costs), 6) if copilot_costs else 0.0,
                "avg_latency_ms": round(mean(copilot_latencies), 2)
                if copilot_latencies
                else 0.0,
                "error_distribution": error_dist,
            },
        }
        snapshot = RuntimeMetricSnapshot(
            snapshot_id=f"runtime_snapshot_{uuid4().hex[:12]}",
            payload=payload,
            created_at=now_iso(),
        )
        if self.repo:
            self.repo.save_runtime_metric_snapshot(snapshot)
        return snapshot


runtime_observer = RuntimeObserver()

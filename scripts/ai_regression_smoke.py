from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.bootstrap import create_services
from backend.schemas import AIRunEvaluationCase, AuthorityLevel, CopilotRequest


CASES = [
    AIRunEvaluationCase(case_id="risk_scan", message="分析 AAPL 风险", page="holdings", symbol="AAPL", expected_tools=["evaluate_policy_risk"]),
    AIRunEvaluationCase(case_id="monitor_explain", message="解释最近一条盯盘事件", page="monitor", expected_tools=["get_monitor_events"]),
]


async def evaluate_case(services, case: AIRunEvaluationCase) -> dict:
    run = services.copilot_service.create_run(
        CopilotRequest(
            message=case.message,
            page=case.page,
            symbol=case.symbol,
            authority_level=AuthorityLevel(case.authority_level.value),
        )
    )
    events = [event async for event in services.copilot_service.stream_run(run.run_id, run.task_id)]
    final = events[-1]
    return {
        "case_id": case.case_id,
        "run_id": run.run_id,
        "task_id": run.task_id,
        "final_type": final.type,
        "tool_calls": [event.payload.get("tool") for event in events if event.type == "tool_call"],
        "final_keys": sorted(final.payload.keys()),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = create_services(db_path=Path(tmp) / "ai-regression.sqlite3", files_root=Path(tmp) / "files")
        async def run_all():
            return await asyncio.gather(*(evaluate_case(services, case) for case in CASES))

        results = asyncio.run(run_all())
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

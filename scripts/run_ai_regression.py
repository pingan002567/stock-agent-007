from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.schemas import AIRunEvaluationCase

try:
    from tests.test_ai_regression import (
        STRUCTURAL_CASES,
        run_evaluation_case,
    )
except ImportError:
    print("ERROR: Could not import regression test helpers.", file=sys.stderr)
    print("Make sure tests/test_ai_regression.py exists.", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    # Force stub runtime for structural tests (fast, no API key needed)
    os.environ.setdefault("WORKBENCH_DEERFLOW_MODE", "stub")

    # Use env var to enable full-coverage (requires real LLM runtime)
    full = os.environ.get("AI_REGRESSION_FULL", "").lower() in ("1", "true", "yes")

    cases: list[AIRunEvaluationCase] = list(STRUCTURAL_CASES)
    if full:
        try:
            from tests.test_ai_regression import FULL_COVERAGE_CASES

            for c in FULL_COVERAGE_CASES:
                # Unwrap pytest.param if needed
                if hasattr(c, "values"):
                    cases.extend(c.values)
                else:
                    cases.append(c)
        except ImportError:
            print("Full-coverage cases not available, running structural only.", file=sys.stderr)

    tmp = tempfile.mkdtemp()
    try:
        client = TestClient(
            create_app(
                db_path=Path(tmp) / "regression.sqlite3",
                files_root=Path(tmp) / "files",
            )
        )
    except Exception as exc:
        print(f"ERROR: Failed to create test app: {exc}", file=sys.stderr)
        return 1

    results: list[dict] = []
    failed = 0
    total = len(cases)
    timeout_per_case = int(os.environ.get("AI_REGRESSION_TIMEOUT", "30"))

    print(f"AI Regression Runner — {total} case(s) ({'full' if full else 'structural'})")
    print(f"  timeout per case: {timeout_per_case}s")
    print()

    for i, case in enumerate(cases, 1):
        label = f"[{i}/{total}] {case.case_id}"
        print(f"  {label}  ", end="", flush=True)

        start = time.time()
        try:
            result = run_evaluation_case(client, case)
            elapsed = time.time() - start
        except Exception as exc:
            elapsed = time.time() - start
            result = type(
                "obj",
                (),
                {
                    "passed": False,
                    "notes": [str(exc)],
                    "run_id": None,
                    "task_id": None,
                    "final_type": None,
                    "actual_skills": [],
                    "actual_tools": [],
                    "missing_final_keys": [],
                },
            )()

        status = "PASS" if result.passed else "FAIL"
        marker = "+" if result.passed else "x"
        print(f"\r  {label}  [{marker}] {status}  ({elapsed:.1f}s)")
        if not result.passed:
            failed += 1
            for note in result.notes:
                print(f"          note: {note}")

        results.append(
            {
                "case_id": case.case_id,
                "passed": result.passed,
                "elapsed_seconds": round(elapsed, 2),
                "notes": result.notes,
                "run_id": result.run_id,
                "task_id": result.task_id,
                "final_type": result.final_type,
                "actual_skills": result.actual_skills,
                "actual_tools": result.actual_tools,
                "missing_final_keys": result.missing_final_keys,
            }
        )

    summary = {
        "total": total,
        "passed": total - failed,
        "failed": failed,
        "full_mode": full,
        "results": results,
    }

    report_path = os.environ.get("AI_REGRESSION_REPORT", "")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n  Report written to {report_path}")

    print(f"\n  Summary: {summary['passed']}/{total} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

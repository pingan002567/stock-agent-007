from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.bootstrap import create_services
from backend.schemas import AuthorityLevel, CopilotRequest


async def run_smoke(message: str, symbol: str) -> int:
    with tempfile.TemporaryDirectory(prefix="deerflow-smoke-") as temp_dir:
        root = Path(temp_dir)
        services = create_services(db_path=root / "smoke.sqlite3", files_root=root / "files")
        run = services.copilot_service.create_run(
            CopilotRequest(
                message=message,
                page="stock",
                symbol=symbol,
                authority_level=AuthorityLevel.A4,
            )
        )

        print("runtime_status=" + json.dumps(services.copilot_service.deerflow.status().to_dict(), ensure_ascii=False))
        event_types: list[str] = []
        final_seen = False
        error_seen = False

        async for event in services.copilot_service.stream_run(run.run_id, run.task_id):
            event_types.append(event.type)
            if event.type == "error":
                error_seen = True
                print("error_payload=" + json.dumps(event.payload, ensure_ascii=False))
            if event.type == "final":
                final_seen = True
                print("final_payload=" + json.dumps(event.payload, ensure_ascii=False))

        print("sse_event_types=" + ",".join(event_types))
        print(f"final_seen={final_seen}")
        print(f"error_seen={error_seen}")
        return 0 if final_seen else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check DeerFlow embedded/stub stream through CopilotService.")
    parser.add_argument("message", nargs="?", default="分析 AAPL 风险")
    parser.add_argument("--symbol", default="AAPL")
    args = parser.parse_args()
    return asyncio.run(run_smoke(args.message, args.symbol))


if __name__ == "__main__":
    raise SystemExit(main())

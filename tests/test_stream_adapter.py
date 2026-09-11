from __future__ import annotations

import asyncio
import math

from backend.agent_runtime.stream_adapter import SSE_PING_FRAME, encode_sse, to_sse
from backend.schemas import SSEEvent


def test_encode_sse_includes_event_name_and_json_data():
    raw = encode_sse(
        SSEEvent(run_id="run_1", task_id="task_1", type="reasoning", payload={"text": "hi"})
    )
    assert raw.startswith("event: reasoning\n")
    assert '"text": "hi"' in raw
    assert raw.endswith("\n\n")


def test_encode_sse_replaces_nan_instead_of_crashing():
    raw = encode_sse(
        SSEEvent(
            run_id="run_1",
            task_id="task_1",
            type="tool_result",
            payload={"weight": math.nan, "nested": {"pnl": math.inf}},
        )
    )
    assert "NaN" not in raw
    assert "Infinity" not in raw
    assert '"weight": null' in raw
    assert '"pnl": null' in raw


def test_to_sse_sends_named_ping_while_upstream_is_idle():
    async def delayed():
        await asyncio.sleep(0.08)
        yield SSEEvent(run_id="run_1", task_id="task_1", type="final", payload={"conclusion": "done"})

    async def collect() -> list[str]:
        return [chunk async for chunk in to_sse(delayed(), ping_interval=0.03)]

    chunks = asyncio.run(collect())
    assert chunks[0] == ": ok\n\n"
    assert chunks[1] == SSE_PING_FRAME
    assert any(chunk == SSE_PING_FRAME for chunk in chunks[2:])
    assert any(chunk.startswith("event: final") for chunk in chunks)
    assert chunks[-1].startswith("event: final")

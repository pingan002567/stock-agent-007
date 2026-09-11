from __future__ import annotations

import asyncio
import json
import math
from contextlib import suppress
from typing import Any, AsyncIterator

from backend.schemas import SSEEvent, model_to_dict

# Named ping events keep WKWebView / CFNetwork EventSource alive. SSE comments
# (`: ping`) keep TCP proxies happy but do not reset WebKit's idle cutoff (~60s).
SSE_PING_INTERVAL_SECONDS = 15.0
SSE_PING_FRAME = "event: ping\ndata: {}\n\n"
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def encode_sse(event: SSEEvent) -> str:
    payload = _json_safe(model_to_dict(event))
    return (
        f"event: {event.type}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, allow_nan=False)}\n\n"
    )


async def to_sse(
    events: AsyncIterator[SSEEvent],
    *,
    ping_interval: float = SSE_PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    # First bytes immediately so the client does not sit on an empty response
    # while the agent runtime is still starting or replaying a checkpoint.
    yield ": ok\n\n"
    yield SSE_PING_FRAME
    agen = events.__aiter__()
    pending: asyncio.Task[SSEEvent] = asyncio.create_task(agen.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=max(ping_interval, 0.01))
            if not done:
                yield SSE_PING_FRAME
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            yield encode_sse(event)
            pending = asyncio.create_task(agen.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending

from __future__ import annotations

import json
from typing import AsyncIterator

from backend.schemas import SSEEvent, model_to_dict


def encode_sse(event: SSEEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(model_to_dict(event), ensure_ascii=False)}\n\n"


async def to_sse(events: AsyncIterator[SSEEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield encode_sse(event)

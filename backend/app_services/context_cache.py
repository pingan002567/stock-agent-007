from __future__ import annotations

import time
from typing import Any


class ContextCache:
    """Per-request in-memory cache with configurable TTL per key.

    Designed to avoid repeated DB/API calls within a short window
    (e.g. multiple consecutive Copilot runs querying the same holdings).
    Not thread-safe — intended for single-request use only.
    """

    def __init__(self, ttl_seconds: int = 10) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.monotonic() - ts < self._ttl_seconds:
            return val
        del self._cache[key]
        return None

    def set(self, key: str, val: Any) -> None:
        self._cache[key] = (time.monotonic(), val)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

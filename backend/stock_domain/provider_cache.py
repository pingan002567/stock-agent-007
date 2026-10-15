from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from typing import Any


class ProviderCache:
    """Thread-safe process-level LRU cache with TTL expiration.

    Features:
    - OrderedDict + RLock for thread-safe LRU eviction
    - TTL expiration per entry (default_ttl or per-set)
    - LRU eviction when maxsize reached
    - Hit/miss statistics
    - Batch invalidation by key prefix
    """

    def __init__(self, maxsize: int = 4096, default_ttl: float = 30.0) -> None:
        self._maxsize = maxsize
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self._misses += 1
                return None
            expire_at, value = item
            if time.time() >= expire_at:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            expire_at = time.time() + (ttl if ttl is not None else self._default_ttl)
            self._store[key] = (expire_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
            "size": len(self._store),
            "maxsize": self._maxsize,
        }

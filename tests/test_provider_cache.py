from __future__ import annotations

import threading
import time

from backend.stock_domain.provider_cache import ProviderCache


def test_get_set() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("k1", "v1")
    assert cache.get("k1") == "v1"


def test_get_miss() -> None:
    cache = ProviderCache()
    assert cache.get("nonexistent") is None


def test_ttl_expiry() -> None:
    cache = ProviderCache()
    cache.set("k1", "v1", ttl=0.01)
    assert cache.get("k1") == "v1"
    time.sleep(0.02)
    assert cache.get("k1") is None


def test_default_ttl() -> None:
    cache = ProviderCache(default_ttl=0.01)
    cache.set("k1", "v1")
    assert cache.get("k1") == "v1"
    time.sleep(0.02)
    assert cache.get("k1") is None


def test_lru_eviction() -> None:
    cache = ProviderCache(maxsize=3, default_ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    # Access 'a' to refresh its LRU position
    cache.get("a")
    # Add 'd' — should evict 'b' (least recently used, not 'a')
    cache.set("d", 4)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_invalidate() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.invalidate("k1")
    assert cache.get("k1") is None
    assert cache.get("k2") == "v2"


def test_invalidate_prefix() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("quote:AAPL", 150.0)
    cache.set("quote:MSFT", 300.0)
    cache.set("history:AAPL", [1, 2, 3])
    cache.invalidate_prefix("quote:")
    assert cache.get("quote:AAPL") is None
    assert cache.get("quote:MSFT") is None
    assert cache.get("history:AAPL") == [1, 2, 3]


def test_clear() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.clear()
    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_stats() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("k1", "v1")
    cache.get("k1")
    cache.get("k1")
    cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == round(2 / 3, 4)
    assert stats["size"] == 1


def test_stats_after_clear() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("k1", "v1")
    cache.get("k1")
    cache.clear()
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_rate"] == 0.0
    assert stats["size"] == 0


def test_thread_safety() -> None:
    cache = ProviderCache(maxsize=100, default_ttl=60)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        for i in range(100):
            try:
                cache.set(f"k{n}_{i}", i)
                cache.get(f"k{n}_{i}")
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"thread errors: {errors}"


def test_expired_key_returns_none_and_updates_stats() -> None:
    cache = ProviderCache()
    cache.set("k1", "v1", ttl=0.01)
    time.sleep(0.02)
    assert cache.get("k1") is None
    stats = cache.stats()
    assert stats["misses"] >= 1


def test_different_ttl_per_entry() -> None:
    cache = ProviderCache(default_ttl=60)
    cache.set("short", "s", ttl=0.01)
    cache.set("long", "l", ttl=60)
    time.sleep(0.02)
    assert cache.get("short") is None
    assert cache.get("long") == "l"

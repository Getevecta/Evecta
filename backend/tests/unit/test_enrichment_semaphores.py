"""Cluster-wide enrichment caps share a Redis slot counter across workers."""
from __future__ import annotations

import asyncio
import threading

import pytest

from app.utils.enrichment_semaphores import (
    LIMITS,
    RedisBoundedSemaphore,
    get_enrichment_semaphores,
    try_acquire_slot_sync,
)


def test_get_enrichment_semaphores_is_singleton():
    a = get_enrichment_semaphores()
    b = get_enrichment_semaphores()
    assert a is b
    assert a.hunter.limit == LIMITS["hunter"] == 20
    assert a.http.limit == 20
    assert a.google_maps.limit == 25
    assert a.context.limit == 20


def test_try_acquire_fail_open_when_redis_missing(monkeypatch):
    monkeypatch.setattr(
        "app.utils.enrichment_semaphores._load_scripts",
        lambda: (None, None),
    )
    assert try_acquire_slot_sync("hunter", 20, "tok") is True


def test_redis_bounded_semaphore_caps_concurrent_holders(monkeypatch):
    held = 0
    max_held = 0
    lock = threading.Lock()
    limit = 2

    def acquire(name, lim, token, now_ms=None):
        nonlocal held, max_held
        with lock:
            if held < lim:
                held += 1
                max_held = max(max_held, held)
                return True
            return False

    def release(name, token):
        nonlocal held
        with lock:
            held -= 1

    monkeypatch.setattr(
        "app.utils.enrichment_semaphores.try_acquire_slot_sync", acquire
    )
    monkeypatch.setattr(
        "app.utils.enrichment_semaphores.release_slot_sync", release
    )

    gate = RedisBoundedSemaphore("hunter", limit)
    release_section = asyncio.Event()

    async def hold():
        async with gate:
            await release_section.wait()

    async def run():
        tasks = [asyncio.create_task(hold()) for _ in range(6)]
        # Let waiters poll until two are inside.
        for _ in range(40):
            await asyncio.sleep(0.02)
            with lock:
                if max_held >= limit and held == limit:
                    break
        assert max_held == limit
        assert held == limit
        release_section.set()
        await asyncio.gather(*tasks)
        assert held == 0

    asyncio.run(run())


def test_redis_bounded_semaphore_releases_local_slot_on_acquire_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("redis down hard")

    monkeypatch.setattr(
        "app.utils.enrichment_semaphores.try_acquire_slot_sync", boom
    )

    gate = RedisBoundedSemaphore("http", 1)

    async def run():
        with pytest.raises(RuntimeError, match="redis down hard"):
            async with gate:
                pass
        # Local slot must be free again.
        await asyncio.wait_for(gate._local.acquire(), timeout=0.2)
        gate._local.release()

    asyncio.run(run())

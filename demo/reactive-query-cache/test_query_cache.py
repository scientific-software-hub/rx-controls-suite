"""Unit tests for QueryCache semantics — no live SCADA required.

All tests run against a synthetic ``SyntheticUpstream`` that records subscribe
and dispose calls so we can assert the dedup invariant (N component subs → 1
upstream sub) without needing Tango or EPICS.

Run with:
    uv run --with pytest pytest test_query_cache.py -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

# ── path bootstrap ────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))

import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler

from query_cache import QueryCache


# ── synthetic upstream ────────────────────────────────────────────────────────

class SyntheticUpstream:
    """A cold, controllable Observable factory for testing.

    Each subscription:
    - increments ``subscribe_count``
    - emits ``initial_value`` immediately (feeds replay(1) cache)
    - stays live (does NOT complete)
    - increments ``dispose_count`` on dispose
    """

    def __init__(self, initial_value: float = 42.0):
        self.subscribe_count = 0
        self.dispose_count   = 0
        self.initial_value   = initial_value
        self._observers: list = []

    def source_factory(self, key: str) -> rx.Observable:
        upstream = self

        def subscribe(observer, scheduler=None):
            upstream.subscribe_count += 1
            upstream._observers.append(observer)
            observer.on_next(upstream.initial_value)   # seed replay(1)

            def dispose():
                upstream.dispose_count += 1
                try:
                    upstream._observers.remove(observer)
                except ValueError:
                    pass

            return dispose

        return rx.create(subscribe)

    def emit(self, value: float):
        """Push a value to all currently-subscribed observers."""
        for obs in list(self._observers):
            obs.on_next(value)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_cache(upstream: SyntheticUpstream, *, gc_ms: int = 10_000) -> QueryCache:
    """Create a QueryCache backed by *upstream*, running on the current event loop."""
    loop      = asyncio.get_event_loop()
    scheduler = AsyncIOScheduler(loop)
    return QueryCache(
        scheduler,
        upstream.source_factory,
        poll_ms=1_000,
        stale_ms=5_000,
        gc_ms=gc_ms,
    )


# ── test: dedup ───────────────────────────────────────────────────────────────

def test_dedup_three_subscribers_one_upstream_sub():
    """N components watching the same key → exactly 1 upstream subscribe."""

    async def _run():
        upstream = SyntheticUpstream()
        cache    = make_cache(upstream)

        received = []
        d1 = cache.observe("ring.current").subscribe(on_next=received.append)
        d2 = cache.observe("ring.current").subscribe(on_next=received.append)
        d3 = cache.observe("ring.current").subscribe(on_next=received.append)

        # Initial value emitted synchronously on first upstream subscribe;
        # replay(1) delivers it to d2 and d3 from the cache.
        assert upstream.subscribe_count == 1, (
            f"Expected 1 upstream subscribe, got {upstream.subscribe_count}"
        )
        assert cache.metrics()["active_upstream_subs"] == 1
        assert cache.metrics()["total_observers"]      == 3

        d1.dispose()
        d2.dispose()
        d3.dispose()
        cache.close()

    asyncio.run(_run())


def test_dedup_two_different_keys_two_upstream_subs():
    """Two different keys each get their own upstream subscription."""

    async def _run():
        upstream = SyntheticUpstream()
        cache    = make_cache(upstream)

        d1 = cache.observe("ring.current").subscribe(on_next=lambda v: None)
        d2 = cache.observe("sector04.orbit_x").subscribe(on_next=lambda v: None)

        assert upstream.subscribe_count == 2, (
            f"Expected 2 upstream subscribes for 2 keys, got {upstream.subscribe_count}"
        )
        assert cache.metrics()["active_upstream_subs"] == 2

        d1.dispose()
        d2.dispose()
        cache.close()

    asyncio.run(_run())


# ── test: last-value cache (replay(1)) ────────────────────────────────────────

def test_late_subscriber_gets_cached_last_value_immediately():
    """A subscriber arriving after the upstream has emitted sees the latest value."""

    async def _run():
        upstream = SyntheticUpstream(initial_value=99.5)
        cache    = make_cache(upstream)

        # First subscriber — seeds the cache with 99.5.
        first_values: list = []
        d1 = cache.observe("ring.current").subscribe(on_next=first_values.append)

        # Upstream emits a new value (97.3) — d1 should receive it.
        upstream.emit(97.3)
        assert 97.3 in first_values

        # Second subscriber arrives *after* 97.3 was emitted.
        # Thanks to replay(1), it gets 97.3 immediately — no wait for next poll.
        late_values: list = []
        d2 = cache.observe("ring.current").subscribe(on_next=late_values.append)

        assert late_values == [97.3], (
            f"Expected replay of 97.3, got {late_values}"
        )
        # Still only 1 upstream sub — dedup holds.
        assert upstream.subscribe_count == 1

        d1.dispose()
        d2.dispose()
        cache.close()

    asyncio.run(_run())


# ── test: gc teardown ─────────────────────────────────────────────────────────

def test_gc_tears_down_upstream_after_grace_period():
    """Upstream stays live through gc_ms; disconnects after the timer fires."""

    async def _run():
        upstream = SyntheticUpstream()
        cache    = make_cache(upstream, gc_ms=50)   # 50 ms grace

        d = cache.observe("ring.current").subscribe(on_next=lambda v: None)
        assert upstream.subscribe_count == 1
        assert cache.metrics()["active_upstream_subs"] == 1

        # Dispose last observer — arms the 50 ms gc timer.
        d.dispose()
        assert cache.metrics()["active_upstream_subs"] == 1, (
            "Upstream should stay live during gc window"
        )
        assert cache.metrics()["keys"]["ring.current"]["gc_pending"] is True

        # Wait past gc_ms — upstream should be torn down.
        await asyncio.sleep(0.15)

        assert upstream.dispose_count == 1, (
            f"Expected upstream to be disposed after gc, dispose_count={upstream.dispose_count}"
        )
        assert cache.metrics()["active_upstream_subs"] == 0
        assert cache.metrics()["keys"]["ring.current"]["upstream_live"] is False

        cache.close()

    asyncio.run(_run())


# ── test: gc cancel on re-subscribe ──────────────────────────────────────────

def test_resubscribe_within_gc_window_reuses_warm_upstream():
    """A new observer inside the gc window cancels teardown and reuses the upstream."""

    async def _run():
        upstream = SyntheticUpstream(initial_value=55.0)
        cache    = make_cache(upstream, gc_ms=200)   # 200 ms grace

        d1 = cache.observe("ring.current").subscribe(on_next=lambda v: None)
        assert upstream.subscribe_count == 1

        # Last observer leaves — gc timer arms.
        d1.dispose()
        assert cache.metrics()["keys"]["ring.current"]["gc_pending"] is True

        # New observer arrives WITHIN grace window.
        new_values: list = []
        d2 = cache.observe("ring.current").subscribe(on_next=new_values.append)

        # gc timer should be cancelled — upstream NOT reconnected.
        assert cache.metrics()["keys"]["ring.current"]["gc_pending"] is False
        assert upstream.subscribe_count == 1, (
            "Upstream should NOT have been re-subscribed — still the same connection"
        )
        # And the new observer should have gotten the cached last value.
        assert new_values == [55.0], f"Expected replay of 55.0, got {new_values}"

        # Wait well past original gc_ms — upstream should remain live.
        await asyncio.sleep(0.1)
        assert cache.metrics()["active_upstream_subs"] == 1

        d2.dispose()
        cache.close()

    asyncio.run(_run())


# ── test: metrics accuracy ────────────────────────────────────────────────────

def test_metrics_observer_counts():
    """metrics() accurately reports observer counts per key."""

    async def _run():
        upstream = SyntheticUpstream()
        cache    = make_cache(upstream)

        d1 = cache.observe("ring.current").subscribe(on_next=lambda v: None)
        d2 = cache.observe("ring.current").subscribe(on_next=lambda v: None)
        d3 = cache.observe("sector04.orbit_x").subscribe(on_next=lambda v: None)

        m = cache.metrics()
        assert m["total_observers"]                              == 3
        assert m["keys"]["ring.current"]["observers"]           == 2
        assert m["keys"]["sector04.orbit_x"]["observers"]       == 1
        assert m["active_upstream_subs"]                        == 2

        d1.dispose()
        m2 = cache.metrics()
        assert m2["keys"]["ring.current"]["observers"]          == 1
        assert m2["total_observers"]                            == 2

        d2.dispose()
        d3.dispose()
        cache.close()

    asyncio.run(_run())


def test_metrics_ops_per_sec():
    """ops_per_sec = active_upstream_subs / (poll_ms / 1000)."""

    async def _run():
        upstream = SyntheticUpstream()
        loop      = asyncio.get_event_loop()
        scheduler = AsyncIOScheduler(loop)
        cache     = QueryCache(scheduler, upstream.source_factory,
                               poll_ms=500, stale_ms=5_000, gc_ms=10_000)

        d1 = cache.observe("a").subscribe(on_next=lambda v: None)
        d2 = cache.observe("b").subscribe(on_next=lambda v: None)

        m = cache.metrics()
        assert m["active_upstream_subs"] == 2
        # 2 keys × (1000 / 500) = 4.0 ops/sec
        assert m["ops_per_sec"] == 4.0, f"Expected 4.0 ops/sec, got {m['ops_per_sec']}"

        d1.dispose()
        d2.dispose()
        cache.close()

    asyncio.run(_run())

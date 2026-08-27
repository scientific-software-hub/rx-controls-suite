"""Tests for guarded_by / abort_on — Scenario B (interlock) of the demo.

The property that matters for the live demo: when the facility's interlock
trips, the acquisition stops *and* the detector genuinely receives an
``abort`` before the pipeline is allowed to finish — not a fire-and-forget
side effect that can race the caller's own shutdown (see recipes.py's
abort_on docstring for the bug this guards against).
"""

import asyncio
from datetime import timedelta

import httpx
import reactivex as rx
from reactivex.subject import Subject

from conftest import FakeDetectorContext
from facilities import FacilityHealth
from recipes import guarded_by


def _run(coro):
    return asyncio.run(coro)


def _health(interlock_ok: bool) -> FacilityHealth:
    return FacilityHealth(
        beam_available=True, interlock_ok=interlock_ok, orbit_ok=True, current=100.0, source="fake"
    )


def test_guarded_by_completes_source_after_abort_settles():
    abort_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/command/abort"):
            abort_calls.append(1)
        return httpx.Response(200, json={"sequence_id": 1})

    ctx = FakeDetectorContext(handler)
    health: Subject = Subject()
    source = rx.interval(timedelta(milliseconds=10))  # never completes on its own

    completions = []

    async def run():
        disposable = source.pipe(guarded_by(health, ctx)).subscribe(
            on_next=lambda _: None,
            on_completed=lambda: completions.append(True),
        )
        await asyncio.sleep(0.05)
        health.on_next(_health(interlock_ok=True))  # healthy tick — must not cut the source
        await asyncio.sleep(0.05)
        assert completions == []
        health.on_next(_health(interlock_ok=False))  # interlock trips
        await asyncio.sleep(0.2)
        disposable.dispose()

    _run(run())

    assert completions == [True]
    assert abort_calls == [1]  # exactly once


def test_guarded_by_ignores_healthy_ticks():
    abort_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        abort_calls.append(request.url.path)
        return httpx.Response(200, json={"sequence_id": 1})

    ctx = FakeDetectorContext(handler)
    health: Subject = Subject()
    source = rx.interval(timedelta(milliseconds=10))

    completions = []

    async def run():
        disposable = source.pipe(guarded_by(health, ctx)).subscribe(
            on_next=lambda _: None,
            on_completed=lambda: completions.append(True),
        )
        for _ in range(5):
            health.on_next(_health(interlock_ok=True))
            await asyncio.sleep(0.02)
        disposable.dispose()

    _run(run())

    assert completions == []
    assert abort_calls == []

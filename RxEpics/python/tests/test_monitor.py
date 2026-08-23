"""Tests for monitor_pv — push value Observable, and its resilience properties."""

import asyncio
import gc
import warnings

import numpy as np
import pytest
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.monitor import monitor_pv
from conftest import FakeResponse, FakeStatus


def _run(coro):
    return asyncio.run(coro)


def test_monitor_emits_floats_on_updates(fake_ctx):
    """Values flow through as plain floats — the unchanged public contract."""
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        d = monitor_pv("X", fake_ctx).subscribe(on_next=results.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv._sub.fire(FakeResponse(np.array([1.0])))
        pv._sub.fire(FakeResponse(np.array([2.5])))
        await asyncio.sleep(0.05)
        d.dispose()

    _run(run())
    assert results == [1.0, 2.5]


def test_monitor_callback_is_two_argument(fake_ctx):
    """Regression test: caproto's asyncio client calls func(sub, response).

    A 1-arg callback (the original bug) would raise TypeError inside
    Subscription.fire and never reach on_next.
    """
    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_pv("X", fake_ctx).subscribe(on_next=lambda v: None, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        # A stray TypeError here means the registered callback has the wrong arity.
        pv._sub.fire(FakeResponse(np.array([1.0])))
        await asyncio.sleep(0.01)

    _run(run())  # would raise if the callback signature were wrong


def test_monitor_survives_garbage_collection(fake_ctx):
    """Regression test: caproto stores callbacks by weakref, so the closure
    needs an explicit strong referent.

    This deliberately does not capture the Disposable returned by
    ``.subscribe()`` — every example in this library discards it too (they
    run until Ctrl+C instead). If the callback's only strong referent were
    that Disposable's AutoDetachObserver chain, it would form a reference
    cycle back through the closure's own captured ``observer``, and this
    gc.collect() would reap it — reproducing the original bug one level
    removed. See the _KEEPALIVE note in monitor.py.
    """
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_pv("X", fake_ctx).subscribe(on_next=results.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        gc.collect()
        pv = fake_ctx.pvs["X"]
        assert pv._sub.live_callback_count == 1, "callback was garbage-collected"
        pv._sub.fire(FakeResponse(np.array([3.0])))
        await asyncio.sleep(0.05)

    _run(run())
    assert results == [3.0]


def test_monitor_dispose_awaits_clear_without_warning(fake_ctx):
    """Regression test: Subscription.clear() is a coroutine in the asyncio
    client; dropping it without awaiting produced a RuntimeWarning and never
    tore down the CA subscription."""
    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        d = monitor_pv("X", fake_ctx).subscribe(on_next=lambda v: None, scheduler=scheduler)
        await asyncio.sleep(0.05)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            d.dispose()
            await asyncio.sleep(0.05)  # let the scheduled clear() coroutine run
        assert fake_ctx.pvs["X"]._sub.cleared

    _run(run())


def test_bad_payload_logs_and_stream_continues(fake_ctx, caplog):
    """A conversion failure is logged, not swallowed, and does not end the
    monitor — the next good value still arrives."""
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_pv("X", fake_ctx).subscribe(on_next=results.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        with caplog.at_level("WARNING", logger="rxepics.monitor"):
            pv._sub.fire(FakeResponse(np.array(["not-a-float"])))  # unconvertible
            await asyncio.sleep(0.01)
            pv._sub.fire(FakeResponse(np.array([9.0])))
            await asyncio.sleep(0.05)

    _run(run())
    assert results == [9.0]
    assert any("failed to convert" in rec.message for rec in caplog.records)


def test_non_normal_status_logs_and_stream_continues(fake_ctx, caplog):
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_pv("X", fake_ctx).subscribe(on_next=results.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        with caplog.at_level("WARNING", logger="rxepics.monitor"):
            pv._sub.fire(FakeResponse(np.array([1.0]), status=FakeStatus(success=False, name="ECA_TIMEOUT")))
            await asyncio.sleep(0.01)
            pv._sub.fire(FakeResponse(np.array([9.0])))
            await asyncio.sleep(0.05)

    _run(run())
    assert results == [9.0]
    assert any("non-normal CA status" in rec.message for rec in caplog.records)


def test_setup_failure_reaches_on_error(fake_ctx):
    """A PV that cannot be located is a terminal failure — this is the one
    case that legitimately reaches on_error."""
    fake_ctx.fail_lookup.add("MISSING")
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()
        monitor_pv("MISSING", fake_ctx).subscribe(
            on_next=lambda v: None,
            on_error=lambda e: (errors.append(e), done.set()),
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert len(errors) == 1

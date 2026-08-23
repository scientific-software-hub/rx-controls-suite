"""Tests for monitor_errors — per-update failures carried as messages."""

import asyncio

import numpy as np
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.errors import PvUpdateError
from rxepics.monitor import monitor_errors
from conftest import FakeResponse, FakeStatus


def _run(coro):
    return asyncio.run(coro)


def test_monitor_errors_emits_on_bad_payload(fake_ctx):
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_errors("X", fake_ctx).subscribe(on_next=errors.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv._sub.fire(FakeResponse(np.array(["not-a-float"])))
        await asyncio.sleep(0.05)

    _run(run())
    assert len(errors) == 1
    assert isinstance(errors[0], PvUpdateError)
    assert errors[0].pv_name == "X"
    assert isinstance(errors[0].cause, ValueError)


def test_monitor_errors_emits_on_non_normal_status(fake_ctx):
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_errors("X", fake_ctx).subscribe(on_next=errors.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv._sub.fire(FakeResponse(np.array([1.0]), status=FakeStatus(success=False, name="ECA_TIMEOUT")))
        await asyncio.sleep(0.05)

    _run(run())
    assert len(errors) == 1
    assert errors[0].cause is None
    assert "ECA_TIMEOUT" in str(errors[0])


def test_monitor_errors_ignores_good_values(fake_ctx):
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_errors("X", fake_ctx).subscribe(on_next=errors.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv._sub.fire(FakeResponse(np.array([1.0])))
        await asyncio.sleep(0.05)

    _run(run())
    assert errors == []


def test_monitor_errors_survives_multiple_failures(fake_ctx):
    """The stream survives to deliver a second error — it must never
    terminate itself on a bad update."""
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_errors("X", fake_ctx).subscribe(on_next=errors.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv._sub.fire(FakeResponse(np.array(["bad"])))
        await asyncio.sleep(0.01)
        pv._sub.fire(FakeResponse(np.array(["bad again"])))
        await asyncio.sleep(0.05)

    _run(run())
    assert len(errors) == 2


def test_monitor_pv_and_monitor_errors_share_one_subscription(fake_ctx):
    """caproto dedupes Subscription objects by parameters — verifies the two
    update-driven observables really do share one CA subscription."""
    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        monitor_errors("X", fake_ctx).subscribe(on_next=lambda e: None, scheduler=scheduler)
        from rxepics.monitor import monitor_pv
        monitor_pv("X", fake_ctx).subscribe(on_next=lambda v: None, scheduler=scheduler)
        await asyncio.sleep(0.05)

    _run(run())
    # both subscribe() calls resolved to the same FakePV -> same FakeSubscription
    assert len(fake_ctx.pvs) == 1
    assert fake_ctx.pvs["X"]._sub.live_callback_count == 2

"""Tests for connection_status — push Observable[bool] of CA connection state."""

import asyncio

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.connection import connection_status


def _run(coro):
    return asyncio.run(coro)


def test_initial_state_is_false_when_never_connected(fake_ctx):
    """caproto never fires connection_state_callback for a PV that has not
    yet connected — the synthetic initial False is what makes this total."""
    states = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        connection_status("X", fake_ctx).subscribe(on_next=states.append, scheduler=scheduler)
        await asyncio.sleep(0.05)

    _run(run())
    assert states == [False]


def test_emits_true_on_connect(fake_ctx):
    states = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        connection_status("X", fake_ctx).subscribe(on_next=states.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv.connection_state_callback.fire(pv, "connected")
        await asyncio.sleep(0.05)

    _run(run())
    assert states == [False, True]


def test_duplicate_transitions_suppressed(fake_ctx):
    states = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        connection_status("X", fake_ctx).subscribe(on_next=states.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv.connection_state_callback.fire(pv, "connected")
        pv.connection_state_callback.fire(pv, "connected")  # duplicate
        pv.connection_state_callback.fire(pv, "disconnected")
        await asyncio.sleep(0.05)

    _run(run())
    assert states == [False, True, False]


def test_dispose_removes_callback_token(fake_ctx):
    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        d = connection_status("X", fake_ctx).subscribe(on_next=lambda v: None, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        assert len(pv.connection_state_callback._callbacks) == 1
        d.dispose()
        assert len(pv.connection_state_callback._callbacks) == 0

    _run(run())


def test_late_subscriber_sees_current_connected_state(fake_ctx):
    """run=True replays the current state to a subscriber that arrives after
    the PV already connected."""
    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        # First subscriber drives the PV to "connected" via a raw fire, then
        # disposes, before the second subscriber ever attaches.
        early_states = []
        d = connection_status("X", fake_ctx).subscribe(on_next=early_states.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        pv = fake_ctx.pvs["X"]
        pv.connection_state_callback.fire(pv, "connected")
        await asyncio.sleep(0.01)
        d.dispose()

        # New subscription: synthetic False, then run=True immediately
        # replays the PV's actual current state ("connected").
        late_states = []
        connection_status("X", fake_ctx).subscribe(on_next=late_states.append, scheduler=scheduler)
        await asyncio.sleep(0.05)
        assert late_states == [False, True]

    _run(run())

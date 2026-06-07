"""Tests for monitor_attribute — push event Observable."""

import asyncio
from unittest.mock import patch

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango.monitor import monitor_attribute
from rxtango.context import TangoContext

from conftest import FakeDeviceProxy


def _run(coro):
    return asyncio.run(coro)


def test_monitor_emits_on_events():
    """monitor_attribute emits a value for each Tango event callback."""
    fake_proxy = FakeDeviceProxy(read_value=0.0)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            disposable = monitor_attribute("device", "attr").subscribe(
                on_next=results.append,
                scheduler=scheduler,
            )

            # Allow _start() to complete (run_in_executor + event_id assignment)
            await asyncio.sleep(0.1)

            # Simulate two Tango events arriving from C++ thread
            fake_proxy.fire(1.0)
            await asyncio.sleep(0)  # let call_soon_threadsafe dispatch
            fake_proxy.fire(2.0)
            await asyncio.sleep(0)

            disposable.dispose()

    _run(run())

    assert results == [1.0, 2.0]


def test_monitor_calls_unsubscribe_on_dispose():
    """dispose() calls proxy.unsubscribe_event with the correct event_id."""
    fake_proxy = FakeDeviceProxy()

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            disposable = monitor_attribute("device", "attr").subscribe(
                on_next=lambda _: None,
                scheduler=scheduler,
            )
            # Allow _start() to run fully: run_in_executor + event_id assignment
            await asyncio.sleep(0.1)
            disposable.dispose()

    _run(run())

    assert 1 in fake_proxy.unsubscribed


def test_monitor_never_completes():
    """monitor_attribute does not emit on_completed while running."""
    fake_proxy = FakeDeviceProxy()
    completions = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            disposable = monitor_attribute("device", "attr").subscribe(
                on_next=lambda _: None,
                on_completed=lambda: completions.append(True),
                scheduler=scheduler,
            )
            await asyncio.sleep(0.1)
            fake_proxy.fire(99.0)
            await asyncio.sleep(0)
            disposable.dispose()

    _run(run())

    assert completions == [], "monitor_attribute must never call on_completed"


def test_monitor_propagates_subscription_error():
    """When proxy.subscribe_event raises, the error propagates via on_error."""
    errors = []

    class ErrorProxy(FakeDeviceProxy):
        def subscribe_event(self, attr, evt_type, callback):
            raise RuntimeError("event system unavailable")

    fake_proxy = ErrorProxy()

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            monitor_attribute("device", "attr").subscribe(
                on_next=lambda _: None,
                on_error=lambda e: (errors.append(e), done.set()),
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)

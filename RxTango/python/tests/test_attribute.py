"""Tests for read_attribute — single-shot attribute read Observable."""

import asyncio
from unittest.mock import patch

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango.attribute import read_attribute
from rxtango.context import TangoContext

from conftest import FakeDeviceProxy


def _run(coro):
    """Helper: run a coroutine in a fresh event loop and return the result."""
    return asyncio.run(coro)


def test_read_attribute_emits_value_and_completes():
    """read_attribute emits exactly one value (the attribute's .value) then completes."""
    fake_proxy = FakeDeviceProxy(read_value=3.14)
    results, errors, completions = [], [], []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            read_attribute("sys/tg_test/1", "double_scalar").subscribe(
                on_next=results.append,
                on_error=errors.append,
                on_completed=lambda: (completions.append(True), done.set()),
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert results == [3.14]
    assert errors == []
    assert completions == [True]


def test_read_attribute_propagates_error():
    """When the proxy raises, the error is forwarded via on_error."""
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        def failing_proxy(*_):
            raise RuntimeError("connection failed")

        with patch.object(TangoContext, "get_proxy", side_effect=failing_proxy):
            read_attribute("bad/device/1", "attr").subscribe(
                on_next=lambda _: None,
                on_error=lambda e: (errors.append(e), done.set()),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_read_attribute_emits_integer_value():
    """read_attribute passes through integer values unchanged."""
    fake_proxy = FakeDeviceProxy(read_value=7)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            read_attribute("device", "long_scalar").subscribe(
                on_next=results.append,
                on_error=lambda e: done.set(),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [7]

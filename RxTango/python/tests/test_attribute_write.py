"""Tests for write_attribute — single-shot attribute write Observable."""

import asyncio
from unittest.mock import patch

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango.attribute_write import write_attribute
from rxtango.context import TangoContext

from conftest import FakeDeviceProxy


def _run(coro):
    return asyncio.run(coro)


def test_write_attribute_emits_written_value():
    """write_attribute re-emits the written value so chains continue."""
    fake_proxy = FakeDeviceProxy()
    results, completions = [], []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            write_attribute("device", "double_scalar_w", 9.81).subscribe(
                on_next=results.append,
                on_error=lambda e: done.set(),
                on_completed=lambda: (completions.append(True), done.set()),
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert results == [9.81]
    assert completions == [True]


def test_write_attribute_calls_proxy_write():
    """write_attribute passes the value to proxy.write_attribute."""
    fake_proxy = FakeDeviceProxy()

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            write_attribute("device", "double_scalar_w", 2.71).subscribe(
                on_next=lambda _: None,
                on_error=lambda e: done.set(),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert fake_proxy._written == [("double_scalar_w", 2.71)]


def test_write_attribute_propagates_error():
    """When proxy.write_attribute raises, the error propagates via on_error."""
    errors = []

    def failing_proxy(*_):
        raise OSError("device unreachable")

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", side_effect=failing_proxy):
            write_attribute("device", "attr", 0.0).subscribe(
                on_next=lambda _: None,
                on_error=lambda e: (errors.append(e), done.set()),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert len(errors) == 1
    assert isinstance(errors[0], OSError)


def test_write_attribute_chaining():
    """Written value feeds the next flat_map — the chain pattern works."""
    import reactivex.operators as ops

    fake_proxy = FakeDeviceProxy()
    second_written = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            write_attribute("device", "attr1", 5.0).pipe(
                ops.flat_map(lambda v: write_attribute("device", "attr2", v * 2))
            ).subscribe(
                on_next=second_written.append,
                on_error=lambda e: done.set(),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert second_written == [10.0]

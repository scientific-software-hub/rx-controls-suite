"""Tests for TangoClient fluent builder."""

import asyncio
from unittest.mock import patch

import pytest
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango.client import TangoClient
from rxtango.context import TangoContext

from conftest import FakeDeviceProxy


def _run(coro):
    return asyncio.run(coro)


def test_empty_chain_raises():
    """subscribe() on an empty chain raises RuntimeError."""
    with pytest.raises(RuntimeError, match="empty"):
        TangoClient().subscribe()


def test_read_emits_value():
    """TangoClient.read() emits the attribute value."""
    fake_proxy = FakeDeviceProxy(read_value=7.0)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            TangoClient() \
                .read("device", "attr") \
                .subscribe(
                    on_next=results.append,
                    on_completed=done.set,
                    scheduler=scheduler,
                )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [7.0]


def test_read_map_write_chain():
    """read → map → write pipes value correctly through each step."""
    fake_proxy = FakeDeviceProxy(read_value=4.0)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            TangoClient() \
                .read("device", "attr") \
                .map(lambda v: v * 2.0) \
                .write("device", "attr_w") \
                .subscribe(
                    on_next=results.append,
                    on_completed=done.set,
                    scheduler=scheduler,
                )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    # map(v * 2) → write(8.0) → emits 8.0
    assert results == [8.0]
    assert fake_proxy._written == [("attr_w", 8.0)]


def test_write_static_value():
    """write(device, attr, value) writes a static value ignoring the chain."""
    fake_proxy = FakeDeviceProxy(read_value=99.0)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            TangoClient() \
                .read("device", "attr") \
                .write("device", "attr_w", value=0.0) \
                .subscribe(
                    on_next=results.append,
                    on_completed=done.set,
                    scheduler=scheduler,
                )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [0.0]
    assert fake_proxy._written == [("attr_w", 0.0)]


def test_write_callable_value():
    """write(device, attr, fn) applies fn to the previous value."""
    fake_proxy = FakeDeviceProxy(read_value=5.0)
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            TangoClient() \
                .read("device", "attr") \
                .write("device", "attr_w", value=lambda v: -v) \
                .subscribe(
                    on_next=results.append,
                    on_completed=done.set,
                    scheduler=scheduler,
                )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [-5.0]
    assert fake_proxy._written == [("attr_w", -5.0)]


def test_execute_in_chain():
    """TangoClient.execute() issues a command and passes the result forward."""
    fake_proxy = FakeDeviceProxy(command_result="RUNNING")
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            TangoClient() \
                .execute("device", "Status") \
                .subscribe(
                    on_next=results.append,
                    on_completed=done.set,
                    scheduler=scheduler,
                )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == ["RUNNING"]


def test_monitor_must_be_first_step():
    """monitor() raises RuntimeError when called after another step."""
    with pytest.raises(RuntimeError, match="first step"):
        TangoClient() \
            .read("device", "attr") \
            .monitor("device", "other")

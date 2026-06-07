"""Tests for execute_command — single-shot command execution Observable."""

import asyncio
from unittest.mock import patch

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango.command import execute_command
from rxtango.context import TangoContext

from conftest import FakeDeviceProxy


def _run(coro):
    return asyncio.run(coro)


def test_execute_command_emits_result():
    """execute_command emits the command result and completes."""
    fake_proxy = FakeDeviceProxy(command_result="ON")
    results, completions = [], []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            execute_command("device", "State").subscribe(
                on_next=results.append,
                on_error=lambda e: done.set(),
                on_completed=lambda: (completions.append(True), done.set()),
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert results == ["ON"]
    assert completions == [True]


def test_execute_command_without_argin():
    """execute_command with no argin calls proxy.command_inout(name) only."""
    called_with = []

    class TrackingProxy(FakeDeviceProxy):
        def command_inout(self, name, argin=None):
            called_with.append((name, argin))
            return "result"

    fake_proxy = TrackingProxy()

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            execute_command("device", "Status").subscribe(
                on_next=lambda _: None,
                on_error=lambda e: done.set(),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert called_with == [("Status", None)]


def test_execute_command_with_argin():
    """execute_command with argin passes it through to proxy.command_inout."""
    called_with = []

    class TrackingProxy(FakeDeviceProxy):
        def command_inout(self, name, argin=None):
            called_with.append((name, argin))
            return 42

    fake_proxy = TrackingProxy()

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", return_value=fake_proxy):
            execute_command("device", "SomeCmd", argin=99).subscribe(
                on_next=lambda _: None,
                on_error=lambda e: done.set(),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert called_with == [("SomeCmd", 99)]


def test_execute_command_propagates_error():
    """When the proxy raises, the error propagates via on_error."""
    errors = []

    def failing_proxy(*_):
        raise RuntimeError("command failed")

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()

        with patch.object(TangoContext, "get_proxy", side_effect=failing_proxy):
            execute_command("device", "BadCmd").subscribe(
                on_next=lambda _: None,
                on_error=lambda e: (errors.append(e), done.set()),
                on_completed=done.set,
                scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)

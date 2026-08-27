"""Tests for DectrisClient — the fluent builder."""

import asyncio

import httpx
import pytest

from rxdectris.client import DectrisClient

from conftest import FakeDetectorContext


def _run(coro):
    return asyncio.run(coro)


def test_read_execute_execute_chain():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/detector/api/1.8.0/config/count_time":
            return httpx.Response(200, json={"value": 0.01})
        return httpx.Response(200, json={"sequence_id": 1})

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        done = asyncio.Event()
        DectrisClient(ctx).read("count_time").execute("arm").execute("trigger").subscribe(
            on_next=results.append, on_completed=done.set
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert seen == [
        "/detector/api/1.8.0/config/count_time",
        "/detector/api/1.8.0/command/arm",
        "/detector/api/1.8.0/command/trigger",
    ]
    assert results == [1]  # trigger's sequence_id, chained from arm's response


def test_monitor_must_be_first_step():
    ctx = FakeDetectorContext(lambda request: httpx.Response(200, json={}))
    client = DectrisClient(ctx).read("count_time")
    with pytest.raises(RuntimeError):
        client.monitor()


def test_subscribe_on_empty_chain_raises():
    ctx = FakeDetectorContext(lambda request: httpx.Response(200, json={}))
    with pytest.raises(RuntimeError):
        DectrisClient(ctx).subscribe()

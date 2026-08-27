"""Tests for read_config / write_config — GET/PUT .../detector/api/1.8.0/config/<param>."""

import asyncio
import json

import httpx

from rxdectris.config import read_config, write_config
from rxdectris.errors import SimplonError

from conftest import FakeDetectorContext


def _run(coro):
    return asyncio.run(coro)


def test_read_config_emits_json_body_and_completes():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/detector/api/1.8.0/config/count_time"
        return httpx.Response(200, json={"value": 0.5, "value_type": "float", "unit": "s"})

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        done = asyncio.Event()
        read_config("count_time", ctx).subscribe(
            on_next=results.append, on_completed=done.set
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [{"value": 0.5, "value_type": "float", "unit": "s"}]


def test_write_config_sends_value_body_and_emits_changed_params():
    def handler(request):
        assert request.method == "PUT"
        assert request.url.path == "/detector/api/1.8.0/config/count_time"
        assert json.loads(request.content) == {"value": 0.01}
        return httpx.Response(200, json=["count_time", "frame_time"])

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        done = asyncio.Event()
        write_config("count_time", 0.01, ctx).subscribe(
            on_next=results.append, on_completed=done.set
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [["count_time", "frame_time"]]


def test_read_config_propagates_http_error():
    def handler(request):
        return httpx.Response(404, json={"error": "not found"})

    ctx = FakeDetectorContext(handler)
    errors = []

    async def run():
        done = asyncio.Event()
        read_config("nonexistent", ctx).subscribe(
            on_error=lambda e: (errors.append(e), done.set()),
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert len(errors) == 1
    assert isinstance(errors[0], SimplonError)
    assert errors[0].status_code == 404

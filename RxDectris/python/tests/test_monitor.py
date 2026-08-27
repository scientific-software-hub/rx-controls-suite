"""Tests for monitor_images — the Monitor subsystem HTTP poller."""

import asyncio

import httpx

from rxdectris.models import Frame
from rxdectris.monitor import monitor_images

from conftest import FakeDetectorContext


def _run(coro):
    return asyncio.run(coro)


def test_monitor_images_skips_empty_and_emits_frame():
    calls = {"n": 0}

    def handler(request):
        assert request.url.path == "/monitor/api/1.8.0/images/next"
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(408)  # nothing buffered yet
        return httpx.Response(
            200,
            json={
                "series_id": 1,
                "series_unique_id": "abc",
                "image_id": 0,
                "real_time": 0.01,
                "start_time": 0.0,
                "stop_time": 0.01,
                "counts": 999.0,
            },
        )

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        disposable = monitor_images(ctx, poll_ms=10, timeout_ms=5).subscribe(
            on_next=results.append
        )
        for _ in range(50):
            if results:
                break
            await asyncio.sleep(0.02)
        disposable.dispose()

    _run(run())
    assert len(results) >= 1
    assert isinstance(results[0], Frame)
    assert results[0].counts == 999.0


def test_monitor_images_mode_selects_endpoint():
    seen_paths = []

    def handler(request):
        seen_paths.append(request.url.path)
        return httpx.Response(408)

    ctx = FakeDetectorContext(handler)

    async def run():
        disposable = monitor_images(ctx, poll_ms=10, mode="monitor").subscribe(
            on_next=lambda _: None
        )
        await asyncio.sleep(0.05)
        disposable.dispose()

    _run(run())
    assert seen_paths
    assert all(p == "/monitor/api/1.8.0/images/monitor" for p in seen_paths)


def test_monitor_images_never_completes():
    def handler(request):
        return httpx.Response(408)

    ctx = FakeDetectorContext(handler)
    completions = []

    async def run():
        disposable = monitor_images(ctx, poll_ms=10).subscribe(
            on_next=lambda _: None, on_completed=lambda: completions.append(True)
        )
        await asyncio.sleep(0.05)
        disposable.dispose()

    _run(run())
    assert completions == []

"""Tests for stream2 — the Stream V2 push Observable — and configure_stream."""

import asyncio
import json

import httpx

from rxdectris.models import Frame, SeriesEnd, SeriesStart
from rxdectris.stream import configure_stream, stream2

from conftest import FakeDetectorContext


def _run(coro):
    return asyncio.run(coro)


_START = {
    "type": "start",
    "series_id": 1,
    "series_unique_id": "abc123",
    "count_time": 0.01,
    "frame_time": 0.011,
    "number_of_images": 2,
    "image_size_x": 64,
    "image_size_y": 64,
}
_IMAGE_0 = {
    "type": "image",
    "series_id": 1,
    "series_unique_id": "abc123",
    "image_id": 0,
    "real_time": 0.01,
    "start_time": 0.0,
    "stop_time": 0.01,
    "counts": 12345.0,
}
_IMAGE_1 = {**_IMAGE_0, "image_id": 1, "counts": 12200.0}
_END = {"type": "end", "series_id": 1, "series_unique_id": "abc123"}


def test_stream2_decodes_start_image_end_in_order():
    def handler(request):
        return httpx.Response(200)

    ctx = FakeDetectorContext(handler)
    ctx.stream.push(_START)
    ctx.stream.push(_IMAGE_0)
    ctx.stream.push(_IMAGE_1)
    ctx.stream.push(_END)

    results = []

    async def run():
        disposable = stream2(ctx).subscribe(on_next=results.append)
        # Give the background reader loop time to drain all four queued messages.
        for _ in range(20):
            if len(results) >= 4:
                break
            await asyncio.sleep(0.05)
        disposable.dispose()

    _run(run())

    assert len(results) == 4
    assert isinstance(results[0], SeriesStart)
    assert results[0].series_id == 1
    assert results[0].number_of_images == 2
    assert isinstance(results[1], Frame)
    assert results[1].image_id == 0
    assert results[1].counts == 12345.0
    assert isinstance(results[2], Frame)
    assert results[2].image_id == 1
    assert isinstance(results[3], SeriesEnd)
    assert results[3].series_id == 1


def test_stream2_never_completes_on_its_own():
    def handler(request):
        return httpx.Response(200)

    ctx = FakeDetectorContext(handler)
    ctx.stream.push(_END)
    completions = []

    async def run():
        disposable = stream2(ctx).subscribe(
            on_next=lambda _: None, on_completed=lambda: completions.append(True)
        )
        await asyncio.sleep(0.1)
        disposable.dispose()

    _run(run())
    assert completions == []


def test_stream2_dispose_stops_the_reader():
    def handler(request):
        return httpx.Response(200)

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        disposable = stream2(ctx).subscribe(on_next=results.append)
        await asyncio.sleep(0.05)
        disposable.dispose()
        await asyncio.sleep(0.05)
        ctx.stream.push(_START)  # pushed after dispose — must not be observed
        await asyncio.sleep(0.1)

    _run(run())
    assert results == []


def test_configure_stream_writes_format_then_mode():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[request.url.path.rsplit("/", 1)[-1]])

    ctx = FakeDetectorContext(handler)

    async def run():
        done = asyncio.Event()
        configure_stream(ctx).subscribe(on_completed=done.set)
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert seen == [
        ("/stream/api/1.8.0/config/format", {"value": "cbor"}),
        ("/stream/api/1.8.0/config/mode", {"value": "enabled"}),
    ]

"""Tests for acquire_series — the detector-lifecycle recipe.

These are the tests the demo's live-fault story depends on: whichever branch
fires (clean completion, an errored command, or external disposal), teardown
happens exactly once and issues the correct command — `disarm` on the clean
path, `abort` everywhere else.
"""

import asyncio

import httpx

from rxdectris.errors import DetectorStateError
from rxdectris.models import Frame, SeriesEnd, SeriesStart
from rxdectris.recipes import acquire_series

from conftest import FakeDetectorContext

API = "/detector/api/1.8.0/command"
_START = {
    "type": "start", "series_id": 1, "series_unique_id": "abc",
    "count_time": 0.01, "frame_time": 0.011,
    "number_of_images": 2, "image_size_x": 64, "image_size_y": 64,
}


def _image(image_id, counts):
    return {
        "type": "image", "series_id": 1, "series_unique_id": "abc",
        "image_id": image_id, "real_time": 0.01, "start_time": 0.0,
        "stop_time": 0.01, "counts": counts,
    }


_END = {"type": "end", "series_id": 1, "series_unique_id": "abc"}


def _run(coro):
    return asyncio.run(coro)


def test_acquire_series_happy_path_disarms_exactly_once():
    calls: list[str] = []
    ctx_holder = {}

    def handler(request):
        path = request.url.path
        if path == f"{API}/arm":
            ctx_holder["ctx"].stream.push(_START)
            return httpx.Response(200, json={"sequence_id": 1})
        if path == f"{API}/trigger":
            ctx_holder["ctx"].stream.push(_image(0, 100.0))
            ctx_holder["ctx"].stream.push(_image(1, 90.0))
            ctx_holder["ctx"].stream.push(_END)
            return httpx.Response(200, content=b"")
        if path == f"{API}/disarm":
            calls.append("disarm")
            return httpx.Response(200, json={"sequence_id": 2})
        if path == f"{API}/abort":
            calls.append("abort")
            return httpx.Response(200, json={"sequence_id": 3})
        return httpx.Response(200, json=["ok"])  # config writes

    ctx = FakeDetectorContext(handler)
    ctx_holder["ctx"] = ctx
    results = []

    async def run():
        done = asyncio.Event()
        acquire_series(ctx, frames=2, count_time=0.01).subscribe(
            on_next=results.append,
            on_completed=done.set,
            on_error=lambda e: done.set(),
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await asyncio.sleep(0.05)  # let any stray teardown call land before asserting

    _run(run())

    assert [type(r).__name__ for r in results] == ["SeriesStart", "Frame", "Frame", "SeriesEnd"]
    assert isinstance(results[0], SeriesStart)
    assert isinstance(results[-1], SeriesEnd)
    assert calls == ["disarm"]


def test_acquire_series_aborts_on_command_error():
    """trigger fails (e.g. injected detector_error) — teardown issues abort, not disarm."""
    calls: list[str] = []
    ctx_holder = {}

    def handler(request):
        path = request.url.path
        if path == f"{API}/arm":
            ctx_holder["ctx"].stream.push(_START)
            return httpx.Response(200, json={"sequence_id": 1})
        if path == f"{API}/trigger":
            return httpx.Response(409, json={"error": "detector_error"})
        if path == f"{API}/disarm":
            calls.append("disarm")
            return httpx.Response(200, json={"sequence_id": 2})
        if path == f"{API}/abort":
            calls.append("abort")
            return httpx.Response(200, json={"sequence_id": 3})
        return httpx.Response(200, json=["ok"])

    ctx = FakeDetectorContext(handler)
    ctx_holder["ctx"] = ctx
    errors = []

    async def run():
        done = asyncio.Event()
        acquire_series(ctx, frames=2, count_time=0.01).subscribe(
            on_next=lambda _: None,
            on_error=lambda e: (errors.append(e), done.set()),
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await asyncio.sleep(0.05)

    _run(run())

    assert len(errors) == 1
    assert isinstance(errors[0], DetectorStateError)
    assert calls == ["abort"]


def test_acquire_series_disposal_mid_stream_aborts_exactly_once():
    calls: list[str] = []
    ctx_holder = {}

    def handler(request):
        path = request.url.path
        if path == f"{API}/arm":
            ctx_holder["ctx"].stream.push(_START)
            ctx_holder["ctx"].stream.push(_image(0, 100.0))
            # Deliberately never push SeriesEnd — the consumer is disposed first.
            return httpx.Response(200, json={"sequence_id": 1})
        if path == f"{API}/trigger":
            return httpx.Response(200, content=b"")
        if path == f"{API}/disarm":
            calls.append("disarm")
            return httpx.Response(200, json={"sequence_id": 2})
        if path == f"{API}/abort":
            calls.append("abort")
            return httpx.Response(200, json={"sequence_id": 3})
        return httpx.Response(200, json=["ok"])

    ctx = FakeDetectorContext(handler)
    ctx_holder["ctx"] = ctx
    holder: dict = {}
    results = []

    def on_next(item):
        results.append(item)
        if isinstance(item, Frame):
            holder["disposable"].dispose()

    async def run():
        holder["disposable"] = acquire_series(ctx, frames=2, count_time=0.01).subscribe(
            on_next=on_next, on_error=lambda e: None
        )
        await asyncio.sleep(0.3)

    _run(run())

    assert any(isinstance(r, Frame) for r in results)
    assert not any(isinstance(r, SeriesEnd) for r in results)
    assert calls == ["abort"]


def test_acquire_series_subscribes_to_stream_before_arm():
    """If the DCU emits `start` synchronously inside the arm response (as the
    fake does), the recipe must already be listening — proving subscribe-then-arm
    ordering, not arm-then-subscribe.
    """
    ctx_holder = {}

    def handler(request):
        path = request.url.path
        if path == f"{API}/arm":
            ctx_holder["ctx"].stream.push(_START)  # would be lost if not yet subscribed
            ctx_holder["ctx"].stream.push(_END)
            return httpx.Response(200, json={"sequence_id": 1})
        if path == f"{API}/trigger":
            return httpx.Response(200, content=b"")
        return httpx.Response(200, json=["ok"])

    ctx = FakeDetectorContext(handler)
    ctx_holder["ctx"] = ctx
    results = []

    async def run():
        done = asyncio.Event()
        acquire_series(ctx, frames=0, count_time=0.01).subscribe(
            on_next=results.append, on_completed=done.set, on_error=lambda e: done.set()
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert [type(r).__name__ for r in results] == ["SeriesStart", "SeriesEnd"]

"""Tests for send_command and the six lifecycle verbs."""

import asyncio
import json

import httpx

from rxdectris.command import abort, arm, cancel, disarm, initialize, send_command, trigger
from rxdectris.errors import DetectorStateError

from conftest import FakeDetectorContext


def _run(coro):
    return asyncio.run(coro)


def test_arm_emits_sequence_id():
    def handler(request):
        assert request.method == "PUT"
        assert request.url.path == "/detector/api/1.8.0/command/arm"
        assert json.loads(request.content) == {}
        return httpx.Response(200, json={"sequence_id": 7})

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        done = asyncio.Event()
        arm(ctx).subscribe(on_next=results.append, on_completed=done.set)
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [7]


def test_initialize_emits_none_for_empty_body():
    def handler(request):
        assert request.url.path == "/detector/api/1.8.0/command/initialize"
        return httpx.Response(200, content=b"")

    ctx = FakeDetectorContext(handler)
    results = []

    async def run():
        done = asyncio.Event()
        initialize(ctx).subscribe(on_next=results.append, on_completed=done.set)
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert results == [None]


def test_trigger_sends_count_time_override():
    def handler(request):
        assert request.url.path == "/detector/api/1.8.0/command/trigger"
        assert json.loads(request.content) == {"value": 0.02}
        return httpx.Response(200, content=b"")

    ctx = FakeDetectorContext(handler)
    async def run():
        done = asyncio.Event()
        trigger(ctx, count_time=0.02).subscribe(on_completed=done.set)
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())


def test_illegal_transition_raises_detector_state_error():
    """Trigger before arm — SIMPLON returns an error status; we surface 409 as DetectorStateError."""

    def handler(request):
        return httpx.Response(409, json={"error": "detector not armed"})

    ctx = FakeDetectorContext(handler)
    errors = []

    async def run():
        done = asyncio.Event()
        trigger(ctx).subscribe(on_error=lambda e: (errors.append(e), done.set()))
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert len(errors) == 1
    assert isinstance(errors[0], DetectorStateError)
    assert errors[0].status_code == 409


def test_disarm_abort_cancel_hit_correct_paths():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"sequence_id": 1})

    ctx = FakeDetectorContext(handler)

    async def run():
        for obs in (disarm(ctx), abort(ctx), cancel(ctx)):
            done = asyncio.Event()
            obs.subscribe(on_completed=done.set)
            await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert seen == [
        "/detector/api/1.8.0/command/disarm",
        "/detector/api/1.8.0/command/abort",
        "/detector/api/1.8.0/command/cancel",
    ]


def test_send_command_is_the_shared_primitive():
    def handler(request):
        assert request.url.path == "/detector/api/1.8.0/command/hv_reset"
        return httpx.Response(200, content=b"")

    ctx = FakeDetectorContext(handler)
    async def run():
        done = asyncio.Event()
        send_command("hv_reset", ctx).subscribe(on_completed=done.set)
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())

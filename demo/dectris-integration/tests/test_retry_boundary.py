"""The most important test in this demo: process_with() retries D.LAB
without ever touching the detector.

A D.LAB job that settles with status="failed" is a *value*, not an rx
error — process_with() has to convert that into an exception itself (see
its docstring) before retry_with_backoff can see anything to retry.
"""

import asyncio

import httpx
import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler

from conftest import FakeDlabContext
from dlab import RxDlab
from recipes import process_with


def _run(coro):
    return asyncio.run(coro)


def test_process_with_retries_until_success_and_never_touches_the_detector():
    """job-1 and job-2 fail, job-3 succeeds — retries=3 is exactly enough.

    upload/run_job are called exactly 3 times each. process_with()'s
    implementation never references a detector object at all — the boundary
    this test protects is structural: retrying the processing stage cannot
    re-trigger an acquisition it holds no handle to.
    """
    calls = {"upload": 0, "run_job": 0}
    FAIL_COUNT = 2

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/datasets"):
            calls["upload"] += 1
            return httpx.Response(200, json={"dataset_id": f"ds-{calls['upload']}"})
        if path == "/api/v1/jobs":
            calls["run_job"] += 1
            job_id = f"job-{calls['run_job']}"
            return httpx.Response(200, json={"job_id": job_id, "status": "queued"})
        if path.startswith("/api/v1/jobs/"):
            n = int(path.rsplit("-", 1)[-1])
            if n <= FAIL_COUNT:
                return httpx.Response(200, json={"job_id": path.rsplit("/", 1)[-1], "status": "failed", "error": "simulated"})
            return httpx.Response(200, json={"job_id": path.rsplit("/", 1)[-1], "status": "succeeded", "result": {"ok": True}})
        return httpx.Response(404)

    ctx = FakeDlabContext(handler)
    dlab = RxDlab(ctx)
    results, errors = [], []

    async def run():
        scheduler = AsyncIOScheduler(asyncio.get_running_loop())
        done = asyncio.Event()
        rx.of({"path": "x.h5", "frames": 5}).pipe(
            process_with(dlab, "demo-processing", retries=3),
        ).subscribe(
            on_next=results.append,
            on_error=lambda e: (errors.append(e), done.set()),
            on_completed=done.set,
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=8.0)

    _run(run())

    assert errors == []
    assert calls["upload"] == 3
    assert calls["run_job"] == 3
    assert len(results) == 1
    assert results[0]["status"] == "succeeded"


def test_process_with_propagates_after_exhausting_retries():
    """processing_failure: every job fails; retries=2 gives up after 2 attempts."""
    calls = {"run_job": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/datasets"):
            return httpx.Response(200, json={"dataset_id": "ds-1"})
        if path == "/api/v1/jobs":
            calls["run_job"] += 1
            return httpx.Response(200, json={"job_id": f"job-{calls['run_job']}", "status": "queued"})
        if path.startswith("/api/v1/jobs/"):
            return httpx.Response(200, json={"job_id": "x", "status": "failed", "error": "simulated processing failure"})
        return httpx.Response(404)

    ctx = FakeDlabContext(handler)
    dlab = RxDlab(ctx)
    errors = []

    async def run():
        scheduler = AsyncIOScheduler(asyncio.get_running_loop())
        done = asyncio.Event()
        rx.of({"path": "x.h5", "frames": 5}).pipe(
            process_with(dlab, "demo-processing", retries=2),
        ).subscribe(
            on_next=lambda _: None,
            on_error=lambda e: (errors.append(e), done.set()),
            on_completed=done.set,
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=8.0)

    _run(run())

    # retries=2 means the operator gives up after attempt_num reaches 2 —
    # 3 total attempts (0, 1, 2) before the final failure propagates.
    assert calls["run_job"] == 3
    assert len(errors) == 1
    assert "processing failed" in str(errors[0])

"""Adapter invariance: the same recipe, run against two different Facility
sources, produces the same acquisition behaviour.

This is the property the whole demo's reveal depends on — "the facility
changed, the experiment recipe didn't" is only true if nothing in
recipes.py ever branches on ``FacilityHealth.source``.
"""

import asyncio

import httpx
import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler

from conftest import FakeDetectorContext
from facilities import FakeFacility, FacilityHealth
from recipes import AcquiredFrame, correlate_with, wait_until_healthy
from rxdectris.recipes import acquire_series


def _run(coro):
    return asyncio.run(coro)


_START = {
    "type": "start", "series_id": 1, "series_unique_id": "abc",
    "count_time": 0.01, "frame_time": 0.011,
    "number_of_images": 3, "image_size_x": 64, "image_size_y": 64,
}


def _image(image_id, counts):
    return {
        "type": "image", "series_id": 1, "series_unique_id": "abc",
        "image_id": image_id, "real_time": 0.01, "start_time": 0.0,
        "stop_time": 0.01, "counts": counts,
    }


_END = {"type": "end", "series_id": 1, "series_unique_id": "abc"}


def _make_detector_ctx():
    holder = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/detector/api/1.8.0/command/arm":
            holder["ctx"].stream.push(_START)
            return httpx.Response(200, json={"sequence_id": 1})
        if path == "/detector/api/1.8.0/command/trigger":
            holder["ctx"].stream.push(_image(0, 100.0))
            holder["ctx"].stream.push(_image(1, 110.0))
            holder["ctx"].stream.push(_image(2, 120.0))
            holder["ctx"].stream.push(_END)
            return httpx.Response(200, content=b"")
        if path in ("/detector/api/1.8.0/command/disarm", "/detector/api/1.8.0/command/abort"):
            return httpx.Response(200, json={"sequence_id": 2})
        return httpx.Response(200, json=["ok"])

    ctx = FakeDetectorContext(handler)
    holder["ctx"] = ctx
    return ctx


def _run_experiment(source_name: str) -> list:
    detector_ctx = _make_detector_ctx()
    results = []

    async def run():
        scheduler = AsyncIOScheduler(asyncio.get_running_loop())
        script = [FacilityHealth(
            beam_available=True, interlock_ok=True, orbit_ok=True, current=123.4, source=source_name,
        )]
        facility = FakeFacility(script, scheduler=scheduler, interval_ms=20)

        done = asyncio.Event()
        rx.concat(
            wait_until_healthy(facility.health()),
            acquire_series(detector_ctx, frames=3, count_time=0.01),
        ).pipe(
            correlate_with(facility),
        ).subscribe(
            on_next=results.append,
            on_completed=done.set,
            on_error=lambda e: done.set(),
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=5.0)

    _run(run())
    return results


def test_same_recipe_same_shape_regardless_of_facility_source():
    epics_results = _run_experiment("epics")
    tango_results = _run_experiment("tango")

    def shape(results):
        kinds = [type(r).__name__ for r in results]
        counts = [r.frame.counts for r in results if isinstance(r, AcquiredFrame)]
        quality = [r.quality_ok for r in results if isinstance(r, AcquiredFrame)]
        return kinds, counts, quality

    assert shape(epics_results) == shape(tango_results)
    # the only thing that's allowed to differ is which facility produced it
    epics_sources = {r.facility.source for r in epics_results if isinstance(r, AcquiredFrame)}
    tango_sources = {r.facility.source for r in tango_results if isinstance(r, AcquiredFrame)}
    assert epics_sources == {"epics"}
    assert tango_sources == {"tango"}


def test_correlate_with_preserves_wire_order():
    results = _run_experiment("fake")
    kinds = [type(r).__name__ if not isinstance(r, AcquiredFrame) else "AcquiredFrame" for r in results]
    assert kinds == ["SeriesStart", "AcquiredFrame", "AcquiredFrame", "AcquiredFrame", "SeriesEnd"]
    image_ids = [r.frame.image_id for r in results if isinstance(r, AcquiredFrame)]
    assert image_ids == [0, 1, 2]

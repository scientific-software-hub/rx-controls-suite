"""Tests for read_pv / read_pv_ts — single-shot read Observable."""

import asyncio

import numpy as np
import pytest
from caproto import AlarmSeverity, CaprotoError
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.channel import read_pv, read_pv_ts
from rxepics.reading import Reading


def _run(coro):
    return asyncio.run(coro)


def test_read_pv_emits_float_and_completes(fake_ctx):
    """The unchanged public contract: a bare float, then completion."""
    results, completions = [], []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        read_pv("X", fake_ctx).subscribe(
            on_next=results.append, on_completed=lambda: completions.append(True),
            scheduler=scheduler,
        )
        await asyncio.sleep(0.05)
        # the fake PV auto-reads 0.0 by default (see FakePV.read in conftest)

    _run(run())
    assert results == [0.0]
    assert completions == [True]


def test_read_pv_ts_emits_reading_with_source_timestamp(fake_ctx):
    """read_pv_ts carries the source timestamp/quality, not read-completion
    wall-clock time."""
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        read_pv_ts("X", fake_ctx).subscribe(on_next=results.append, scheduler=scheduler)
        await asyncio.sleep(0.05)

    _run(run())
    assert len(results) == 1
    reading = results[0]
    assert isinstance(reading, Reading)
    assert reading.value == 0.0
    assert reading.ts == pytest.approx(1_700_000_000.0)
    assert reading.quality == AlarmSeverity.NO_ALARM


def test_read_pv_ts_propagates_setup_failure(fake_ctx):
    fake_ctx.fail_lookup.add("MISSING")
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()
        read_pv_ts("MISSING", fake_ctx).subscribe(
            on_next=lambda r: None,
            on_error=lambda e: (errors.append(e), done.set()),
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    _run(run())
    assert len(errors) == 1
    assert isinstance(errors[0], CaprotoError)

"""Demonstrates a fluent read-transform-write pipeline on EPICS test PVs.

The pipeline:
  1. Read   TEST:CALC     — raw random value from the IOC
  2. Map    |x| * 2 + 1.5 — apply calibration in client
  3. Write  TEST:DOUBLE   — store the calibrated double
  4. Format as string     — pure Python string formatting
  5. Write  TEST:STRING   — store the formatted string on the IOC
  6. Read   TEST:STRING   — read back to confirm

Each step's result feeds directly into the next.
No threads. No callbacks. No intermediate variables.

Usage:
    python pv_pipeline.py

(uses test PVs: TEST:CALC, TEST:DOUBLE, TEST:STRING)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv


async def main():
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    done = asyncio.Event()
    result_holder: list = []

    # Step 1: read raw value
    read_pv("TEST:CALC", ctx).pipe(
        ops.do_action(on_next=lambda v: print(f"  [1] read    TEST:CALC     =  {v}")),

        # Step 2: apply calibration — pure function, no I/O
        ops.map(lambda v: abs(v) * 2.0 + 1.5),
        ops.do_action(on_next=lambda v: print(f"  [2] calibrated            =  {v}")),

        # Step 3: write calibrated double to TEST:DOUBLE
        ops.flat_map(lambda v: write_pv("TEST:DOUBLE", v, ctx)),
        ops.do_action(on_next=lambda v: print(f"  [3] wrote   TEST:DOUBLE   =  {v}")),

        # Step 4: format as string — pure function
        ops.map(lambda v: f"calibrated={v:.4f}"),
        ops.do_action(on_next=lambda v: print(f"  [4] formatted             =  {v!r}")),

        # Step 5: write string to TEST:STRING
        ops.flat_map(lambda v: write_pv("TEST:STRING", v, ctx)),
        ops.do_action(on_next=lambda v: print(f"  [5] wrote   TEST:STRING   =  {v!r}")),

        # Step 6: read back to confirm what the IOC actually has
        ops.flat_map(lambda _: read_pv("TEST:STRING", ctx)),
    ).subscribe(
        on_next=lambda v: result_holder.append(v),
        on_error=lambda e: (print(f"ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()

    if result_holder:
        print(f"\n  Pipeline complete.")
        print(f"  Confirmed on IOC: {result_holder[0]!r}")


if __name__ == "__main__":
    asyncio.run(main())

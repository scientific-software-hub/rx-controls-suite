"""Read-transform-write pipeline: reads a source PV, applies a linear calibration
(gain * value + offset), and writes the result to a destination PV — all expressed
as a single Rx chain.

Demonstrates how Rx turns a multi-step, error-prone imperative sequence into
a composable, readable pipeline with no manual thread management.

Usage:
    python calibration_pipeline.py <src_pv> <dst_pv> <gain> <offset> [interval-ms]

Example (TEST:CALC → scale × 2 + 10 → TEST:DOUBLE, every 1 s):
    python calibration_pipeline.py TEST:CALC TEST:DOUBLE 2.0 10.0 1000
"""

import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv


async def main():
    if len(sys.argv) < 5:
        print(
            "Usage: calibration_pipeline.py <src_pv> <dst_pv> <gain> <offset> [interval-ms]",
            file=sys.stderr,
        )
        sys.exit(1)

    src_pv = sys.argv[1]
    dst_pv = sys.argv[2]
    gain = float(sys.argv[3])
    offset = float(sys.argv[4])
    interval_ms = int(sys.argv[5]) if len(sys.argv) > 5 else 1000

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Pipeline: {src_pv}  →  (× {gain:.2f} + {offset:.2f})  →  {dst_pv}  every {interval_ms} ms")
    print("Ctrl+C to stop")

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # Step 1: read source PV
        ops.flat_map(lambda _: read_pv(src_pv, ctx)),
        # Step 2: apply linear calibration — pure function, no I/O
        ops.map(lambda raw: raw * gain + offset),
        # Step 3: write calibrated value to destination PV
        ops.flat_map(lambda cal: write_pv(dst_pv, cal, ctx)),
        # Step 4: confirm
    ).subscribe(
        on_next=lambda v: print(
            f"[{int(time.time() * 1000)}]  wrote  {v:.6f}  →  {dst_pv}"
        ),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

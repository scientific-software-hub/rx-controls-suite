"""Read two PVs on every tick and print both values with their difference
and their measured timestamp skew.

The two reads are issued in parallel by correlate_snapshot (built on
rx.zip) — no threads, no futures, no locks. The pair is only emitted when
BOTH reads complete successfully, but "both complete" is not "the same
instant": each PV's own timestamp is compared, and the skew between them
is printed alongside the values, not assumed away.

Compare with the naive approach: two sequential reads can be torn by a
value update between them.

Usage:
    python pv_correlate.py <pv1> <pv2> [interval-ms]

Example:
    python pv_correlate.py TEST:DOUBLE TEST:LONG 500
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv_ts
from rxepics.correlate import correlate_snapshot


async def main():
    if len(sys.argv) < 3:
        print("Usage: pv_correlate.py <pv1> <pv2> [interval-ms]", file=sys.stderr)
        sys.exit(1)

    pv1 = sys.argv[1]
    pv2 = sys.argv[2]
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"{'pv1':<16}  {'pv2':<16}  {'difference':<12}  skew (s)")
    print("-" * 68)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # correlate_snapshot fires both reads in parallel and combines
        # their results, exactly like rx.zip — the pair is only emitted
        # when BOTH reads complete successfully, and a failed read
        # propagates as an error, no half-pair. What it adds over a bare
        # zip is c.skew: the measured gap between the two PVs' own
        # timestamps, which "both completed" says nothing about on its own.
        # concat_map (not flat_map): each tick's pair is serialized, so
        # printed lines stay in tick order under load.
        ops.concat_map(
            lambda _: correlate_snapshot(
                read_pv_ts(pv1, ctx),
                read_pv_ts(pv2, ctx),
            ).pipe(
                ops.map(lambda c: (
                    f"{c.values[0]:+16.4f}  {c.values[1]:+16.4f}  "
                    f"{c.values[0] - c.values[1]:+12.4f}  {c.skew:.4f}"
                ))
            )
        )
    ).subscribe(
        on_next=print,
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

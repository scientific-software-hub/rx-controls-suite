"""Poll two PVs on a fixed interval, correlate the readings, and print them
as a pair with their measured timestamp skew.

This demo shows the core Rx value proposition: combining data from multiple
sources with a single expression.

correlate_snapshot(obs1, obs2) issues both reads concurrently and combines
their results only when BOTH have completed — same guarantee as a bare
rx.zip — but also reports the measured gap between the two PVs' own
timestamps, since "both completed" is a claim about arrival, not about
whether the two values describe the same instant.

Compare with the naive approach: two sequential reads can be torn by a value
update between them.

Usage:
    python zip_pvs.py <pv1> <pv2> [interval-ms]

Examples:
    python zip_pvs.py TEST:DOUBLE TEST:LONG
    python zip_pvs.py TEST:DOUBLE TEST:LONG 500
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

from rxepics.channel import read_pv_ts
from rxepics.correlate import correlate_snapshot


async def main():
    if len(sys.argv) < 3:
        print("Usage: zip_pvs.py <pv1> <pv2> [interval-ms]", file=sys.stderr)
        sys.exit(1)

    pv1 = sys.argv[1]
    pv2 = sys.argv[2]
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Correlating {pv1} + {pv2} every {interval_ms} ms — Ctrl+C to stop")
    print(f"{'pv1':<20}  {'pv2':<20}  {'difference':<12}  skew (s)")
    print("-" * 70)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # On each tick, correlate_snapshot fires both reads concurrently.
        # The combiner lambda only runs when BOTH complete successfully.
        # If either read fails, it propagates the error, same as rx.zip.
        # concat_map (not flat_map): each tick's pair is serialized, so
        # printed lines stay in tick order under load.
        ops.concat_map(
            lambda _: correlate_snapshot(
                read_pv_ts(pv1, ctx),
                read_pv_ts(pv2, ctx),
            ).pipe(
                ops.map(lambda c: (c.values[0], c.values[1], c.values[0] - c.values[1], c.skew))
            )
        )
    ).subscribe(
        on_next=lambda t: print(
            f"[{int(time.time() * 1000)}]  {t[0]:+.4f}  |  {t[1]:+.4f}  |  {t[2]:+.4f}  |  skew={t[3]:.4f}s"
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

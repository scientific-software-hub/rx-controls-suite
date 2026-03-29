"""Poll two PVs on a fixed interval, zip the values, and print them as a pair.

This demo shows the core Rx value proposition: combining data from multiple
sources with a single expression.

rx.zip(obs1, obs2) issues both reads concurrently and combines their results
only when BOTH have completed — the pair is always coherent.

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

from rxepics.channel import read_pv


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

    print(f"Zipping {pv1} + {pv2} every {interval_ms} ms — Ctrl+C to stop")
    print(f"{'pv1':<20}  {'pv2':<20}  difference")
    print("-" * 55)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # On each tick, zip fires both reads concurrently.
        # The combiner lambda only runs when BOTH complete successfully.
        # If either read fails, zip propagates the error.
        ops.flat_map(
            lambda _: rx.zip(
                read_pv(pv1, ctx),
                read_pv(pv2, ctx),
            ).pipe(
                ops.map(lambda pair: (pair[0], pair[1], pair[0] - pair[1]))
            )
        )
    ).subscribe(
        on_next=lambda t: print(f"[{int(time.time() * 1000)}]  {t[0]:+.4f}  |  {t[1]:+.4f}  |  {t[2]:+.4f}"),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

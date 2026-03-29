"""Read two PVs simultaneously on every tick and print both values with their difference.

The two reads are issued in parallel by rx.zip — no threads, no futures, no locks.
Both values arrive in the same tick, always in sync.

Compare with the naive approach: two sequential reads can be torn by a value
update between them.

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

from rxepics.channel import read_pv


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

    print(f"{'pv1':<16}  {'pv2':<16}  difference")
    print("-" * 52)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # rx.zip fires both reads in parallel and combines their results.
        # The pair is only emitted when BOTH reads complete successfully.
        # If either read fails, zip propagates the error — no half-pair.
        ops.flat_map(
            lambda _: rx.zip(
                read_pv(pv1, ctx),
                read_pv(pv2, ctx),
            ).pipe(
                ops.map(lambda pair: f"{pair[0]:+16.4f}  {pair[1]:+16.4f}  {pair[0] - pair[1]:+.4f}")
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

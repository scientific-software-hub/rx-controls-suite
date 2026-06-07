"""Sliding average over a rolling window using buffer_with_count.

Polls double_scalar and computes a rolling mean of the last N samples.
No circular buffer, no index arithmetic — one operator.

Mirrors `TangoTestSlidingAverage.java` (`buffer(N, 1)` → `buffer_with_count(N, 1)`).

Usage:
    python sliding_average.py [device] [window] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    window       samples in the rolling window; defaults to 5
    interval-ms  poll interval; defaults to 500
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    window      = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(
        f"Sliding average (N={window}) on {device}  "
        f"every {interval_ms} ms  (Ctrl+C to stop)\n"
    )
    print(f"  {'raw':>14}  {'avg(N={window})':>14}  {'delta':>14}")
    print("  " + "-" * 46)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
        ops.buffer_with_count(count=window, skip=1),
        ops.map(lambda buf: (buf[-1], sum(buf) / len(buf))),
    ).subscribe(
        on_next=lambda pair: print(
            f"  {pair[0]:>+14.6f}  {pair[1]:>14.6f}  {pair[0] - pair[1]:>+14.6f}"
        ),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

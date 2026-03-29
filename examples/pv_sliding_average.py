"""Apply a sliding (rolling) average to a stream of PV readings.

buffer_with_count(N, 1) emits overlapping windows of exactly N consecutive
values, advancing by one sample per tick:

  tick 5: [v1, v2, v3, v4, v5]  → mean of window 1
  tick 6: [v2, v3, v4, v5, v6]  → mean of window 2
  tick 7: [v3, v4, v5, v6, v7]  → mean of window 3

Each window is mapped to its mean. The result is a smoothed signal: high-
frequency noise averages out while slow trends remain visible.
The "noise" column shows how far each raw reading deviates from its smoothed value.

No circular buffer, no index arithmetic, no manual window management —
just buffer_with_count(N, 1) and a mean calculation.

Usage:
    python pv_sliding_average.py <pv_name> [window-size] [interval-ms]

Example:
    python pv_sliding_average.py TEST:CALC 5 400
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
    if len(sys.argv) < 2:
        print("Usage: pv_sliding_average.py <pv_name> [window=5] [interval-ms=400]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    window = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 400

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Sliding average  window={window}  interval={interval_ms} ms — Ctrl+C to stop")
    print(f"(first output after {window} samples)\n")
    print(f"  {'raw':<16}  {'smoothed (n=' + str(window) + ')':<20}  noise (raw - smooth)")
    print("  " + "-" * 62)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # One read per tick.
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        # buffer_with_count(N, 1): sliding window of size N, step 1.
        # Each emission is a List[float] containing the last N values.
        # No output until the first full window has accumulated (N ticks).
        ops.buffer_with_count(window, 1),
        # Compute window mean; keep the latest raw value for comparison.
        ops.map(lambda buf: (buf[-1], sum(buf) / len(buf))),
    ).subscribe(
        on_next=lambda pair: print(f"  {pair[0]:+16.6f}  {pair[1]:+20.6f}  {pair[0] - pair[1]:+.6f}"),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

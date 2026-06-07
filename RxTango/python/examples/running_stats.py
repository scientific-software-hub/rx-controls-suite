"""Live streaming statistics using ops.scan (Welford's online algorithm).

Tracks count, mean, and standard deviation without storing all past values.

Mirrors `TangoTestRunningStats.java`.

Usage:
    python running_stats.py [device] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    interval-ms  defaults to 500
"""

import asyncio
import math
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute


def welford_update(state, x):
    """Welford's online algorithm step: (n, mean, M2) → updated state."""
    n, mean, m2 = state
    n += 1
    delta = x - mean
    mean += delta / n
    m2 += delta * (x - mean)
    return n, mean, m2


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Running stats on {device}  every {interval_ms} ms  (Ctrl+C to stop)\n")
    print(f"  {'n':>6}  {'value':>14}  {'mean':>14}  {'std':>14}")
    print("  " + "-" * 56)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
        ops.scan(welford_update, seed=(0, 0.0, 0.0)),
    ).subscribe(
        on_next=lambda s: print(
            f"  {s[0]:>6}  {0.0:>14.6f}  {s[1]:>14.6f}  "
            f"{math.sqrt(s[2] / s[0]) if s[0] > 1 else 0.0:>14.6f}"
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

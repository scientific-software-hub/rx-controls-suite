"""Live streaming statistics using scan() — O(1) memory, no batch, no waiting.

scan() is the streaming counterpart of reduce(). Where reduce() waits for the
stream to complete and emits one final result, scan() emits the running
accumulation after EVERY new value:

  v1 → Stats(n=1, mean=v1, ...)
  v2 → Stats(n=2, mean=(v1+v2)/2, ...)
  v3 → Stats(n=3, ...)

Compare with pv_stats.py: that script collects N samples into a list, computes
once, and exits. This one runs indefinitely, never allocates a growing list, and
always shows current statistics.

Uses Welford's online algorithm for numerically stable mean and variance —
avoids catastrophic cancellation that naive sum-of-squares suffers with large values.

Usage:
    python pv_running_stats.py <pv_name> [interval-ms]

Example:
    python pv_running_stats.py TEST:CALC 500
"""

import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv


@dataclass(frozen=True)
class Stats:
    """Immutable accumulator updated by scan() on each new value.

    Welford's online algorithm: maintains mean and M2 (sum of squared
    deviations from the current mean) for O(1) stable stddev.
    """

    n: int
    latest: float
    lo: float
    hi: float
    mean: float
    m2: float  # Welford M2 accumulator

    @staticmethod
    def zero() -> "Stats":
        return Stats(0, 0.0, float("inf"), float("-inf"), 0.0, 0.0)

    @staticmethod
    def update(s: "Stats", x: float) -> "Stats":
        n = s.n + 1
        delta = x - s.mean
        mean = s.mean + delta / n          # running mean
        delta2 = x - mean
        m2 = s.m2 + delta * delta2         # Welford M2 accumulator
        return Stats(n, x, min(s.lo, x), max(s.hi, x), mean, m2)

    def stddev(self) -> float:
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else 0.0


async def main():
    if len(sys.argv) < 2:
        print("Usage: pv_running_stats.py <pv_name> [interval-ms=500]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Live statistics  interval={interval_ms} ms — Ctrl+C to stop\n")
    print(f"  {'n':>5}  {'latest':>14}  {'mean':>14}  {'min':>14}  {'max':>14}  {'stddev':>14}")
    print("  " + "-" * 82)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # Read one sample per tick.
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        # scan() folds each value into the running Stats accumulator and emits
        # a new Stats after every single sample — unlike reduce() which only
        # emits when the stream completes.
        ops.scan(Stats.update, Stats.zero()),
        # Skip the seed (n=0) emitted before any real data arrives.
        ops.filter(lambda s: s.n > 0),
    ).subscribe(
        on_next=lambda s: print(
            f"  {s.n:5d}  {s.latest:+14.6f}  {s.mean:+14.6f}  "
            f"{s.lo:+14.6f}  {s.hi:+14.6f}  {s.stddev():14.6f}"
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

"""Collect N samples, compute min/mean/max/std (one shot).

Polls double_scalar, accumulates N values, then prints statistics and exits.

Mirrors `TangoTestStats.java`.

Usage:
    python stats.py [device] [n-samples] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    n-samples    number of samples; defaults to 10
    interval-ms  poll interval; defaults to 500
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


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    n_samples   = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Collecting {n_samples} samples from {device}  (interval={interval_ms} ms) …\n")

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
        ops.take(n_samples),
        ops.to_list(),
    ).subscribe(
        on_next=lambda samples: (
            print(f"  n      = {len(samples)}"),
            print(f"  min    = {min(samples):+.6f}"),
            print(f"  max    = {max(samples):+.6f}"),
            print(f"  mean   = {sum(samples)/len(samples):+.6f}"),
            print(f"  std    = {math.sqrt(sum((x - sum(samples)/len(samples))**2 for x in samples) / len(samples)):+.6f}"),
        ),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await asyncio.wait_for(done.wait(), timeout=60.0)


if __name__ == "__main__":
    asyncio.run(main())

"""Collect N samples of a PV at a fixed rate and compute statistics.

No loop. No counter. No list management. The Rx chain handles all of it:
  interval → take(N) → read each tick → collect → reduce to stats

Usage:
    python pv_stats.py <pv_name> [samples] [interval-ms]

Examples:
    python pv_stats.py TEST:CALC
    python pv_stats.py TEST:CALC 50 500
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
        print("Usage: pv_stats.py <pv_name> [samples] [interval-ms]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Collecting {n} samples of {pv_name} @ {interval_ms} ms intervals...\n")

    counter = 0
    samples: list[float] = []
    done = asyncio.Event()

    def on_next(v: float) -> None:
        nonlocal counter
        counter += 1
        samples.append(v)
        print(f"  [{counter:2d}]  {v:+.6f}")

    def on_completed() -> None:
        if not samples:
            done.set()
            return
        n_actual = len(samples)
        mean = sum(samples) / n_actual
        variance = sum((x - mean) ** 2 for x in samples) / n_actual
        import math
        print(f"\n  n      = {n_actual}")
        print(f"  min    = {min(samples):+.6f}")
        print(f"  max    = {max(samples):+.6f}")
        print(f"  mean   = {mean:+.6f}")
        print(f"  stddev = {math.sqrt(variance):.6f}")
        done.set()

    # interval + take(N): emit exactly N ticks, then complete automatically.
    # flat_map: one read per tick.
    # to_list: Rx handles list allocation and synchronisation.
    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.take(n),
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.do_action(on_next=on_next),
        ops.to_list(),
    ).subscribe(
        on_next=lambda _: None,  # data already consumed by do_action
        on_error=lambda e: (print(f"ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=on_completed,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    asyncio.run(main())

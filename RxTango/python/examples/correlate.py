"""Continuously correlated reads of two attributes using rx.zip + interval.

Every interval tick, both attributes are read in parallel.  The pair is emitted
only when BOTH reads complete.  If either fails, the tick is silently dropped.

Mirrors `TangoTestCorrelate.java`.

Usage:
    python correlate.py [device] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    interval-ms  defaults to 1000
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
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Correlating {device}  every {interval_ms} ms  (Ctrl+C to stop)\n")
    print(f"  {'double_scalar':>16}  {'long_scalar':>14}  {'diff':>14}")
    print("  " + "-" * 50)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(
            lambda _: rx.zip(
                read_attribute(device, "double_scalar"),
                read_attribute(device, "long_scalar"),
            ).pipe(
                ops.catch(lambda e, _: rx.empty()),  # drop failed tick
            )
        ),
    ).subscribe(
        on_next=lambda pair: print(
            f"  {pair[0]:>+16.6f}  {pair[1]:>14}  {pair[0] - float(pair[1]):>+14.6f}"
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

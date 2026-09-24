"""Continuously correlated reads of two attributes, reporting their
measured timestamp skew.

Every interval tick, both attributes are read in parallel via
correlate_snapshot (built on rx.zip).  The pair is emitted only when BOTH
reads complete — same guarantee as a bare zip.  If either fails, the tick
is silently dropped.  Correlated.skew is the measured gap between the two
attributes' own DeviceAttribute.time values, not the read-completion time:
"both completed" says nothing on its own about whether the two values
describe the same instant.

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

from rxtango import read_attribute_ts
from rxtango.correlate import correlate_snapshot


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Correlating {device}  every {interval_ms} ms  (Ctrl+C to stop)\n")
    print(f"  {'double_scalar':>16}  {'long_scalar':>14}  {'diff':>14}  {'skew (s)':>10}")
    print("  " + "-" * 62)

    # concat_map (not flat_map): each tick's pair is serialized, so printed
    # lines stay in tick order under load.
    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.concat_map(
            lambda _: correlate_snapshot(
                read_attribute_ts(device, "double_scalar"),
                read_attribute_ts(device, "long_scalar"),
            ).pipe(
                ops.catch(lambda e, _: rx.empty()),  # drop failed tick
            )
        ),
    ).subscribe(
        on_next=lambda c: print(
            f"  {c.values[0]:>+16.6f}  {c.values[1]:>14}  "
            f"{c.values[0] - float(c.values[1]):>+14.6f}  {c.skew:>10.4f}"
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

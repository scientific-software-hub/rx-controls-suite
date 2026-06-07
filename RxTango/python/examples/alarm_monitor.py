"""Alarm fan-in: poll multiple attributes and filter for threshold violations.

Uses rx.merge to combine several polling streams.  The alarm fires as soon as
any attribute crosses its threshold — each source fails independently.

(The Java version uses Tango events; here we use polling to avoid the Tango
event system, which requires additional server-side configuration.)

Mirrors the intent of `AlarmMonitor.java`.

Usage:
    python alarm_monitor.py [device] [threshold] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    threshold    absolute value threshold; defaults to 300.0
    interval-ms  poll interval per attribute; defaults to 500
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
    threshold   = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    period = timedelta(milliseconds=interval_ms)

    def make_poll(attr: str) -> rx.Observable:
        """Poll *attr* at *period*, tag each value with the attribute name."""
        return rx.interval(period, scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_attribute(device, attr)),
            ops.map(lambda v: (attr, v)),
            ops.catch(lambda e, _: rx.empty()),  # isolate per-device errors
        )

    # Monitor two attributes simultaneously
    sources = [
        make_poll("double_scalar"),
        make_poll("long_scalar"),
    ]

    print(
        f"Alarm monitor on {device}  (threshold |v| > {threshold})"
        f"  (Ctrl+C to stop)\n"
    )

    rx.merge(*sources).pipe(
        ops.filter(lambda item: abs(float(item[1])) > threshold),
    ).subscribe(
        on_next=lambda item: print(f"  ALARM  {item[0]:20s}  = {item[1]}"),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

"""Fan-in alarm monitor: polls N PVs, merges all streams into one, and emits
an alarm line whenever any value exceeds the threshold.

Each PV is polled independently. A failure on one PV does not affect the others
— that sub-stream logs the error and terminates while the rest continue.

This is the fan-in pattern: N independent sources → 1 unified alarm stream.

Usage:
    python alarm_monitor.py <threshold> <interval-ms> <pv_name> [<pv_name2> ...]

Example (alert when |value| > 200, poll every 500 ms):
    python alarm_monitor.py 200 500 TEST:CALC TEST:DOUBLE
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv


async def main():
    if len(sys.argv) < 4:
        print(
            "Usage: alarm_monitor.py <threshold> <interval-ms> <pv_name> [<pv_name2> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    threshold = float(sys.argv[1])
    interval_ms = int(sys.argv[2])
    pv_names = sys.argv[3:]

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(
        f"Monitoring {len(pv_names)} source(s), threshold ±{threshold:.2f}, "
        f"poll every {interval_ms} ms — Ctrl+C to stop"
    )

    # Build one polling+filtering stream per PV, then merge them all.
    # Each stream is independent: an error on one PV doesn't kill the others.
    streams = [
        rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_pv(pv_name, ctx)),
            ops.filter(lambda v: abs(v) > threshold),
            ops.map(
                lambda v, n=pv_name: (
                    f"ALARM  [{datetime.now().isoformat(timespec='milliseconds')}]  "
                    f"{n} = {v:.4f}  (threshold ±{threshold:.2f})"
                )
            ),
            # isolate: a stream error logs and terminates only this sub-stream
            ops.catch(
                lambda e, _, n=pv_name: (
                    print(f"Stream error for {n}: {e} — continuing", file=sys.stderr)
                    or rx.empty()
                )
            ),
        )
        for pv_name in pv_names
    ]

    # merge() interleaves all streams into one; each alarm line is printed as it arrives.
    rx.merge(*streams).subscribe(
        on_next=print,
        on_error=lambda e: print(f"Fatal: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

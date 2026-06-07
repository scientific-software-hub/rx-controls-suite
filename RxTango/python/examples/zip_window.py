"""Time-windowed zip: synchronise two attributes sampled in the same window.

Uses ops.buffer_with_count + rx.zip to collect bursts from two fast-polled
streams and compare samples taken in the same window.

Mirrors `TangoTestZipWindow.java`.

Usage:
    python zip_window.py [device] [window] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    window       samples per window; defaults to 5
    interval-ms  sample rate; defaults to 200
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
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    period = timedelta(milliseconds=interval_ms)

    def make_buffered(attr: str) -> rx.Observable:
        return rx.interval(period, scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_attribute(device, attr)),
            ops.buffer_with_count(count=window, skip=window),  # non-overlapping
        )

    print(f"Time-windowed zip (window={window}) on {device}  (Ctrl+C to stop)\n")

    rx.zip(
        make_buffered("double_scalar"),
        make_buffered("long_scalar"),
    ).subscribe(
        on_next=lambda pair: print(
            f"  doubles={[f'{v:+.2f}' for v in pair[0]]}  "
            f"longs={list(pair[1])}"
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

"""Poll a Tango attribute at a fixed interval — no loop, no thread.

Mirrors the Java pattern:
    Flowable.interval(ms).flatMapSingle(read_attribute)

Usage:
    python poll_attribute.py [device] [attribute] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    attribute    defaults to double_scalar
    interval-ms  defaults to 500
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
    attr        = sys.argv[2] if len(sys.argv) > 2 else "double_scalar"
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Polling {device}/{attr} every {interval_ms} ms  (Ctrl+C to stop)\n")
    print(f"  {'value':>20}")
    print("  " + "-" * 22)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, attr)),
    ).subscribe(
        on_next=lambda v: print(f"  {v:>+20.6f}"),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

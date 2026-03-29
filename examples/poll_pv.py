"""Poll a PV on a fixed interval and stream the values.

No events or polling configuration required on the IOC side.

Usage:
    python poll_pv.py <pv_name> [interval-ms]

Examples:
    python poll_pv.py TEST:CALC
    python poll_pv.py TEST:CALC 500
"""

import asyncio
import sys
import time
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
        print("Usage: poll_pv.py <pv_name> [interval-ms]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Polling {pv_name} every {interval_ms} ms — Ctrl+C to stop")

    # interval() ticks every N ms and triggers a fresh read on each tick.
    # flat_map turns each tick into a one-shot read Observable.
    # No loop. No thread management. No counter.
    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_pv(pv_name, ctx))
    ).subscribe(
        on_next=lambda v: print(f"[{int(time.time() * 1000)}]  {v}"),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

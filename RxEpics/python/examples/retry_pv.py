"""Retry a single-shot read with exponential backoff.

retry_with_backoff() only applies to read_pv/write_pv — a re-subscribe there
means "try the read/write again". CA monitors don't need it: caproto already
re-arms a dropped subscription on its own (see connection_status.py and
resilient_monitor.py for the monitor-side story).

Point this at a PV name that doesn't exist to see it retry and then give up.

Usage:
    python retry_pv.py <pv_name> [max-retries] [base-delay-ms]

Examples:
    python retry_pv.py TEST:CALC
    python retry_pv.py TEST:DOES_NOT_EXIST 5 250
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.retry import retry_with_backoff


async def main():
    if len(sys.argv) < 2:
        print("Usage: retry_pv.py <pv_name> [max-retries] [base-delay-ms]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    max_retries = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    base_delay_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()
    done = asyncio.Event()

    print(f"Reading {pv_name} with up to {max_retries} retries (base delay {base_delay_ms} ms)")

    def on_error(e):
        print(f"gave up: {e}", file=sys.stderr)
        done.set()

    read_pv(pv_name, ctx).pipe(
        retry_with_backoff(max_retries=max_retries, base_delay_ms=base_delay_ms, scheduler=scheduler)
    ).subscribe(
        on_next=lambda v: print(f"value: {v}"),
        on_error=on_error,
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

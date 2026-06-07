"""Retry on transient errors using ops.retry.

Demonstrates ops.retry(n) for simple retries and exponential-backoff retry
using rx.timer + ops.catch for smarter recovery.

Mirrors `TangoTestRetry.java`.

Usage:
    python retry.py [device] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    interval-ms  poll interval; defaults to 500
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


def make_backoff_retry(max_retries: int = 5, base_delay_ms: int = 500):
    """Return an operator that retries with exponential backoff."""
    attempt = [0]

    def handler(source: rx.Observable) -> rx.Observable:
        def catch_fn(exc, _src):
            attempt[0] += 1
            if attempt[0] > max_retries:
                return rx.throw(exc)
            delay = timedelta(milliseconds=base_delay_ms * (2 ** (attempt[0] - 1)))
            print(f"  ERROR: {exc}  (retry {attempt[0]}/{max_retries} in {delay.total_seconds():.1f}s)")
            return rx.timer(delay).pipe(
                ops.flat_map(lambda _: source)
            )

        return source.pipe(ops.catch(catch_fn))

    return lambda src: rx.defer(lambda: make_backoff_retry(max_retries, base_delay_ms)(src))


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Polling with retry on {device}  (Ctrl+C to stop)\n")
    print(f"  {'value':>20}")
    print("  " + "-" * 22)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        # Simple retry: up to 3 immediate retries per tick on error
        ops.flat_map(
            lambda _: read_attribute(device, "double_scalar").pipe(
                ops.retry(3)
            )
        ),
    ).subscribe(
        on_next=lambda v: print(f"  {v:>+20.6f}"),
        on_error=lambda e: print(f"  FATAL: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

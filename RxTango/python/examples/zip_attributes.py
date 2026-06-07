"""Correlated read of two attributes using rx.zip.

rx.zip fires both reads in parallel and emits a single pair only when BOTH
have returned.  If either fails, the error propagates immediately — the pair
is never half-processed.

Mirrors the Java `ZipAttributes` / `TangoTestCorrelate` example.

Usage:
    python zip_attributes.py [device]

    device  defaults to tango://localhost:10000/sys/tg_test/1
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Correlated snapshot from {device}  (single shot)\n")

    rx.zip(
        read_attribute(device, "double_scalar"),
        read_attribute(device, "long_scalar"),
    ).subscribe(
        on_next=lambda pair: print(
            f"  double_scalar = {pair[0]:+.6f}\n"
            f"  long_scalar   = {pair[1]}\n"
            f"  diff          = {pair[0] - float(pair[1]):+.6f}"
        ),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    asyncio.run(main())

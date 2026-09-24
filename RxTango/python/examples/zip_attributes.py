"""Correlated read of two attributes, reporting their measured timestamp skew.

correlate_snapshot (built on rx.zip) fires both reads in parallel and emits
a single pair only when BOTH have returned.  If either fails, the error
propagates immediately — the pair is never half-processed.  The measured
skew between the two attributes' own DeviceAttribute.time values is
reported alongside the diff: two "simultaneous" reads can still be
measurably apart if the device serializes them internally.

Mirrors the Java `ZipAttributes` / `TangoTestCorrelate` example.

Usage:
    python zip_attributes.py [device]

    device  defaults to tango://localhost:10000/sys/tg_test/1
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute_ts
from rxtango.correlate import correlate_snapshot


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Correlated snapshot from {device}  (single shot)\n")

    correlate_snapshot(
        read_attribute_ts(device, "double_scalar"),
        read_attribute_ts(device, "long_scalar"),
    ).subscribe(
        on_next=lambda c: print(
            f"  double_scalar = {c.values[0]:+.6f}\n"
            f"  long_scalar   = {c.values[1]}\n"
            f"  diff          = {c.values[0] - float(c.values[1]):+.6f}\n"
            f"  skew          = {c.skew:.4f}s"
        ),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    asyncio.run(main())

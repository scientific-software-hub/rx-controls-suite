"""Fluent 6-step TangoClient pipeline — the showstopper demo.

Read → calibrate → write → format → write → read back.
No threads.  No callbacks.  No intermediate variables.

Mirrors `TangoTestPipeline.java` and `FluentClient.java`.

Usage:
    python pipeline.py [device]

    device  defaults to tango://localhost:10000/sys/tg_test/1
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import TangoClient


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Fluent pipeline on {device}\n")

    TangoClient() \
        .read(device, "double_scalar") \
        .map(lambda v: (print(f"  [1] read     double_scalar   = {v:+.6f}") or v)) \
        .map(lambda v: abs(v) * 2.0 + 1.5) \
        .map(lambda v: (print(f"  [2] calibrated               = {v:+.6f}") or v)) \
        .write(device, "double_scalar_w") \
        .map(lambda v: (print(f"  [3] wrote    double_scalar_w = {v:+.6f}") or v)) \
        .map(lambda v: f"cal={v:.4f}") \
        .map(lambda s: (print(f"  [4] formatted                = {s!r}") or s)) \
        .write(device, "string_scalar_w") \
        .map(lambda s: (print(f"  [5] wrote    string_scalar_w = {s!r}") or s)) \
        .read(device, "string_scalar_w") \
        .subscribe(
            on_next=lambda v: print(f"\n  Confirmed on device: {v!r}"),
            on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
            on_completed=lambda: (print("  Pipeline complete."), done.set()),
            scheduler=scheduler,
        )

    await asyncio.wait_for(done.wait(), timeout=10.0)


if __name__ == "__main__":
    asyncio.run(main())

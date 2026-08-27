"""Acquire a series with the acquire_series recipe — the full detector lifecycle.

configure -> enable stream -> subscribe -> arm -> trigger -> frames -> disarm,
with unconditional abort-on-error teardown built in. See rxdectris.recipes.

Usage:
    python acquire.py [--frames N] [--count-time SECONDS] [--base-url URL]
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DetectorContext, acquire_series
from rxdectris.models import Frame, SeriesEnd, SeriesStart


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--count-time", type=float, default=0.01)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    ctx = await DetectorContext.get(args.base_url)

    print(f"Acquiring {args.frames} frames @ {args.count_time}s from {args.base_url} …")
    t0 = time.time()

    def on_next(msg):
        if isinstance(msg, SeriesStart):
            print(f"  start   series={msg.series_id} n={msg.number_of_images}")
        elif isinstance(msg, Frame):
            print(f"  frame   id={msg.image_id:<4d} counts={msg.counts:.0f}")
        elif isinstance(msg, SeriesEnd):
            print(f"  end     series={msg.series_id}")

    def on_error(exc):
        print(f"  ERROR: {exc}", file=sys.stderr)
        done.set()

    def on_completed():
        elapsed = time.time() - t0
        print(f"series complete in {elapsed:.2f}s")
        done.set()

    acquire_series(ctx, frames=args.frames, count_time=args.count_time).subscribe(
        on_next=on_next, on_error=on_error, on_completed=on_completed, scheduler=scheduler
    )

    await done.wait()
    await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())

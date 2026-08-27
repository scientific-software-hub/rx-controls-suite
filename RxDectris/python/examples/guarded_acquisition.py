"""Wait for the detector to report `ready`, then acquire — the gate idiom.

Same shape as demo/synchrotron-beamline's `wait_healthy`: a pure timing gate
built from `filter -> take(1) -> ignore_elements()`, sequenced with the
acquisition via `rx.concat`. In the full demo this same idiom gates on
*facility* health instead of detector state — see
demo/dectris-integration/recipes.py::wait_until_healthy.

Usage:
    python guarded_acquisition.py [--frames N] [--base-url URL]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DetectorContext, acquire_series, initialize, monitor_state
from rxdectris.models import DetectorState


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--count-time", type=float, default=0.01)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    ctx = await DetectorContext.get(args.base_url)

    # A fresh simulator (or a just-restarted DCU) starts in "na" — initialize
    # unconditionally before waiting for readiness.
    initialize(ctx).subscribe(
        on_error=lambda e: print(f"initialize: {e}"), scheduler=scheduler
    )
    await asyncio.sleep(0.2)

    wait_ready = monitor_state(ctx, poll_ms=200, scheduler=scheduler).pipe(
        ops.filter(lambda s: s.value in ("idle", "ready")),
        ops.take(1),
        ops.do_action(on_next=lambda s: print(f"detector {s.value} — acquiring")),
        ops.ignore_elements(),
    )

    experiment = rx.concat(
        wait_ready,
        acquire_series(ctx, frames=args.frames, count_time=args.count_time),
    )

    experiment.subscribe(
        on_next=lambda m: print(f"  {type(m).__name__}: {m}"),
        on_completed=lambda: (print("done"), done.set()),
        on_error=lambda e: (print(f"ERROR: {e}", file=sys.stderr), done.set()),
        scheduler=scheduler,
    )

    await done.wait()
    await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())

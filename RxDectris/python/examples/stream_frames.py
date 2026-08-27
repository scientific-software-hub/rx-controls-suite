"""Talk to Stream V2 directly, without the acquire_series recipe.

Demonstrates the ordering constraint the recipe hides: subscribe to the
socket *before* issuing arm, because arm is what triggers the `start`
message — arming first races the ZeroMQ connection.

Usage:
    python stream_frames.py [--frames N] [--base-url URL]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DetectorContext
from rxdectris.command import arm, disarm, trigger
from rxdectris.config import write_config
from rxdectris.models import SeriesEnd
from rxdectris.stream import configure_stream, stream2


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    ctx = await DetectorContext.get(args.base_url)

    # 1. Configure, then subscribe — before arm.
    write_config("nimages", args.frames, ctx).subscribe(scheduler=scheduler)
    await asyncio.sleep(0.1)
    configure_stream(ctx).subscribe(scheduler=scheduler)
    await asyncio.sleep(0.1)

    print("subscribing to Stream V2 …")
    stream2(ctx).pipe(
        ops.take_while(lambda m: not isinstance(m, SeriesEnd), inclusive=True),
    ).subscribe(
        on_next=lambda m: print(f"  {type(m).__name__}: {m}"),
        on_completed=lambda: (print("series complete"), done.set()),
        on_error=lambda e: (print(f"ERROR: {e}", file=sys.stderr), done.set()),
        scheduler=scheduler,
    )

    # 2. Now arm and trigger.
    print("arming …")
    arm(ctx).subscribe(
        on_next=lambda seq: print(f"  armed, sequence_id={seq}"),
        on_error=lambda e: print(f"arm failed: {e}", file=sys.stderr),
        scheduler=scheduler,
    )
    await asyncio.sleep(0.2)
    print("triggering …")
    trigger(ctx).subscribe(scheduler=scheduler)

    await done.wait()
    disarm(ctx).subscribe(scheduler=scheduler)
    await asyncio.sleep(0.1)
    await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())

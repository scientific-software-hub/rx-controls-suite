"""DectrisClient fluent chain — read a config value, arm, trigger.

Same shape as RxTango's `pipeline.py` / RxEpics's `pv_pipeline.py`: build a
chain, subscribe once, execution starts immediately.

Usage:
    python fluent_client.py [--base-url URL]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DectrisClient, DetectorContext


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    ctx = await DetectorContext.get(args.base_url)

    DectrisClient(ctx) \
        .read("count_time") \
        .execute("arm") \
        .execute("trigger") \
        .execute("disarm") \
        .subscribe(
            on_next=print,
            on_completed=done.set,
            on_error=lambda e: (print(f"ERROR: {e}"), done.set()),
            scheduler=scheduler,
        )

    await done.wait()
    await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())

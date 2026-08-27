"""Read the detector's status/state — single-shot Observable.

Usage:
    python read_state.py [base_url]

    base_url  defaults to http://localhost:8080 (simplon_sim)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DetectorContext, read_status


async def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    ctx = await DetectorContext.get(base_url)

    print(f"Reading {base_url}/detector/api/1.8.0/status/state …")

    read_status("state", ctx).subscribe(
        on_next=lambda v: print(f"  state = {v}"),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()
    await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())

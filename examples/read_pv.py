"""Read one or more PVs and print the values.

Usage:
    python read_pv.py <pv_name> [<pv_name2> ...]

Example:
    python read_pv.py TEST:DOUBLE TEST:LONG
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv


async def main():
    pv_names = sys.argv[1:]
    if not pv_names:
        print("Usage: read_pv.py <pv_name> [<pv_name2> ...]", file=sys.stderr)
        sys.exit(1)

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    # Read each PV sequentially using rx.concat so output order matches input order.
    # Each read_pv() is a single-shot Observable: emits one value, then completes.
    done = asyncio.Event()
    remaining = len(pv_names)

    def on_completed():
        nonlocal remaining
        remaining -= 1
        if remaining == 0:
            done.set()

    for name in pv_names:
        read_pv(name, ctx).subscribe(
            on_next=lambda v, n=name: print(f"{n} = {v}"),
            on_error=lambda e, n=name: print(f"{n} ERROR: {e}", file=sys.stderr),
            on_completed=on_completed,
            scheduler=scheduler,
        )

    await done.wait()


if __name__ == "__main__":
    asyncio.run(main())

"""Read one Tango attribute — single-shot Observable.

Equivalent to `caget` but as a reactive stream: emits one value and completes.

Usage:
    python read_attribute.py [device] [attribute]

    device     defaults to tango://localhost:10000/sys/tg_test/1
    attribute  defaults to double_scalar
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxtango import read_attribute


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    attr   = sys.argv[2] if len(sys.argv) > 2 else "double_scalar"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Reading {device}/{attr} …")

    read_attribute(device, attr).subscribe(
        on_next=lambda v: print(f"  value = {v}"),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    asyncio.run(main())

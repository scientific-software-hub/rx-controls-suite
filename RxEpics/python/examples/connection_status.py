"""Watch CA connection transitions for a PV as a stream of booleans.

connection_status() is total from the first emission: it reports False
immediately if the PV has never connected, then True/False on every
transition. Try it against a PV whose IOC you can stop and restart —
`docker compose stop` / `docker compose start` in RxEpics/python — and
watch the link go DOWN and back UP with no client-side action.

Usage:
    python connection_status.py <pv_name>

Example:
    python connection_status.py TEST:CALC
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.connection import connection_status


async def main():
    if len(sys.argv) < 2:
        print("Usage: connection_status.py <pv_name>", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Watching link state for {pv_name} — Ctrl+C to stop")

    connection_status(pv_name, ctx).subscribe(
        on_next=lambda up: print(
            f"[{int(time.time() * 1000)}]  {pv_name}  {'UP' if up else 'DOWN'}"
        ),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

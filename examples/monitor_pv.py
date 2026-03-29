"""Subscribe to CA monitor updates on a PV and print each update.

Unlike poll_pv.py which actively requests values on a timer, monitor_pv.py
receives updates pushed by the IOC whenever the value changes. CA monitors
are a first-class Channel Access feature — no polling configuration needed.

Usage:
    python monitor_pv.py <pv_name>

Example:
    python monitor_pv.py TEST:CALC
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.monitor import monitor_pv


async def main():
    if len(sys.argv) < 2:
        print("Usage: monitor_pv.py <pv_name>", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print(f"Monitoring {pv_name} — Ctrl+C to stop")

    # monitor_pv() wraps a CA subscription: the IOC pushes values, no polling.
    monitor_pv(pv_name, ctx).subscribe(
        on_next=lambda v: print(f"[{int(time.time() * 1000)}]  {v}"),
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

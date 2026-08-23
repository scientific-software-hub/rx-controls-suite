"""The end-to-end resilience demo: values, per-update errors, and link state
as one merged stream — errors and status transitions are messages, not
exceptions that stop the process.

Run this, then in another shell restart the IOC out from under it:

    docker compose stop epics-ioc
    docker compose start epics-ioc

The stream survives: link goes DOWN, no traceback, and once the IOC comes
back the link goes UP and values resume — caproto re-arms the CA
subscription on its own, with no client-side action.

Usage:
    python resilient_monitor.py <pv_name>

Example:
    python resilient_monitor.py TEST:CALC
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.connection import connection_status
from rxepics.monitor import monitor_errors, monitor_pv


async def main():
    if len(sys.argv) < 2:
        print("Usage: resilient_monitor.py <pv_name>", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    def ts():
        return int(time.time() * 1000)

    # Three independent streams, tagged and merged into one console view.
    # Each is a message on the wire, never a terminal notification — a bad
    # update or a dropped link shows up as a line of output, not a crash.
    values = monitor_pv(pv_name, ctx).pipe(rx.operators.map(lambda v: f"[{ts()}]  value      {v}"))
    errors = monitor_errors(pv_name, ctx).pipe(rx.operators.map(lambda e: f"[{ts()}]  BAD UPDATE  {e}"))
    link = connection_status(pv_name, ctx).pipe(
        rx.operators.map(lambda up: f"[{ts()}]  link        {'UP' if up else 'DOWN'}")
    )

    print(f"Resilient monitor on {pv_name} — Ctrl+C to stop")
    print("Try: docker compose stop epics-ioc   (then) docker compose start epics-ioc\n")

    rx.merge(values, errors, link).subscribe(
        on_next=print,
        on_error=lambda e: print(f"FATAL (setup failure): {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

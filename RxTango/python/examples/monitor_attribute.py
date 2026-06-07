"""Subscribe to Tango CHANGE events — push Observable.

Prints each value as it arrives from the device event system.  Unlike polling,
no interval is needed: the device pushes values whenever the attribute changes.

.. note::
    Tango event subscriptions require a properly configured event system
    (zmq ports, event heartbeat from the device server).  This example is NOT
    part of the live demo but is included to show the API.

Usage:
    python monitor_attribute.py [device] [attribute] [event-type]

    device      defaults to tango://localhost:10000/sys/tg_test/1
    attribute   defaults to double_scalar
    event-type  defaults to periodic   (change | periodic | archive)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import monitor_attribute


async def main() -> None:
    device     = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    attr       = sys.argv[2] if len(sys.argv) > 2 else "double_scalar"
    event_type = sys.argv[3] if len(sys.argv) > 3 else "periodic"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(f"Monitoring {device}/{attr} ({event_type} events)  (Ctrl+C to stop)\n")

    monitor_attribute(device, attr, event=event_type).subscribe(
        on_next=lambda v: print(f"  {v}"),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

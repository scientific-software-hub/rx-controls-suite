"""Parallel snapshot of the same attribute from multiple devices.

Uses rx.from_iterable + flat_map to fire all reads concurrently, collecting
results into a list.  Errors from individual devices are replaced with None
via ops.catch so the snapshot continues even if a device is unreachable.

Mirrors `MultiDeviceSnapshot.java`.

Usage:
    python multi_device_snapshot.py [device1] [device2] ...

    Defaults to two reads of sys/tg_test/1 with different attributes
    (attribute names for a quick live test with a single device server).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute


async def main() -> None:
    devices = sys.argv[1:] if len(sys.argv) > 1 else [
        "tango://localhost:10000/sys/tg_test/1",
        "tango://localhost:10000/sys/tg_test/1",
    ]
    attrs = ["double_scalar", "long_scalar"]

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()
    results   = []

    pairs = list(zip(devices, attrs))
    print(f"Parallel snapshot of {len(pairs)} attribute(s):\n")

    rx.from_iterable(pairs).pipe(
        ops.flat_map(
            lambda da: read_attribute(da[0], da[1]).pipe(
                ops.map(lambda v: {"device": da[0], "attr": da[1], "value": v}),
                ops.catch(lambda e, _: rx.of(
                    {"device": da[0], "attr": da[1], "value": None, "error": str(e)}
                )),
            )
        ),
        ops.to_list(),
    ).subscribe(
        on_next=lambda items: [results.extend(items)],
        on_error=lambda e: (print(f"ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await asyncio.wait_for(done.wait(), timeout=10.0)

    for item in results:
        if item.get("error"):
            print(f"  {item['device']}/{item['attr']}  ERROR: {item['error']}")
        else:
            print(f"  {item['device']}/{item['attr']}  = {item['value']}")


if __name__ == "__main__":
    asyncio.run(main())

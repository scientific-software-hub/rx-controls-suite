"""Read multiple PVs IN PARALLEL and print a combined snapshot.

All reads are issued concurrently via flat_map — no threads, no locks,
no futures. The snapshot is only printed once ALL reads complete.

Usage (one-shot):
    python multi_pv_snapshot.py <pv_name> [<pv_name2> ...]

Usage (continuous, repeat every N ms):
    python multi_pv_snapshot.py <interval-ms> <pv_name> [<pv_name2> ...]

Examples:
    python multi_pv_snapshot.py TEST:DOUBLE TEST:LONG TEST:STRING

    python multi_pv_snapshot.py 2000 TEST:DOUBLE TEST:LONG TEST:STRING
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv


def snapshot(pv_names: list[str], ctx: Context) -> rx.Observable:
    """Read all PVs concurrently and emit a list of formatted result strings."""
    # from_iterable streams the list one item at a time.
    # flat_map fires one async read per PV — all run concurrently.
    # catch isolates failures: one bad PV doesn't kill the snapshot.
    # to_list collects all results and emits them as one List[str].
    return rx.from_iterable(pv_names).pipe(
        ops.flat_map(
            lambda name: read_pv(name, ctx).pipe(
                ops.map(lambda v, n=name: f"  {n:<30} = {v}"),
                ops.catch(lambda e, _, n=name: rx.of(f"  {n:<30} ! ERROR: {e}")),
            )
        ),
        ops.to_list(),
    )


async def main():
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: multi_pv_snapshot.py [interval-ms] <pv_name> [<pv_name2> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    interval_ms = 0
    start = 0
    try:
        interval_ms = int(args[0])
        start = 1
    except ValueError:
        pass  # no interval, one-shot

    pv_names = args[start:]
    if not pv_names:
        print("No PV names found.", file=sys.stderr)
        sys.exit(1)

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    def print_snapshot(lines: list[str]) -> None:
        print(f"\nSnapshot @ {datetime.now().isoformat(timespec='seconds')}")
        for line in lines:
            print(line)

    if interval_ms <= 0:
        # One-shot: collect snapshot, print, done.
        done = asyncio.Event()
        snapshot(pv_names, ctx).subscribe(
            on_next=print_snapshot,
            on_error=lambda e: print(f"Fatal: {e}", file=sys.stderr),
            on_completed=done.set,
            scheduler=scheduler,
        )
        await done.wait()
    else:
        # Continuous: repeat snapshot every interval_ms.
        print(f"Polling every {interval_ms} ms — Ctrl+C to stop")
        rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: snapshot(pv_names, ctx))
        ).subscribe(
            on_next=print_snapshot,
            on_error=lambda e: print(f"Fatal: {e}", file=sys.stderr),
            scheduler=scheduler,
        )
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

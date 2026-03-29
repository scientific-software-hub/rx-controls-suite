"""Poll a PV at high frequency but process/display at a lower rate.

sample(display_interval) keeps only the LATEST value arriving in each display
window and silently discards all earlier ones. The IOC is still read at the full
poll rate — the throttle lives in the Rx chain, not on the network.

This is the idiomatic Rx answer to "the device updates faster than I can
process": no time.sleep, no manual frame-drop counter, no shared boolean — one operator.

Usage:
    python pv_throttle.py <pv_name> [poll-ms] [display-ms]

Example (poll every 50 ms, display every 1000 ms — 95% drop rate):
    python pv_throttle.py TEST:CALC 50 1000
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv


async def main():
    if len(sys.argv) < 2:
        print("Usage: pv_throttle.py <pv_name> [poll-ms=50] [display-ms=1000]", file=sys.stderr)
        sys.exit(1)

    pv_name = sys.argv[1]
    poll_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    display_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    drop_pct = (1.0 - poll_ms / display_ms) * 100
    print(
        f"Polling every {poll_ms} ms, displaying every {display_ms} ms "
        f"({drop_pct:.0f}% drop rate) — Ctrl+C to stop\n"
    )

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    polled = 0
    displayed = 0

    def on_polled(_: float) -> None:
        nonlocal polled
        polled += 1

    def on_displayed(v: float) -> None:
        nonlocal displayed
        displayed += 1
        print(f"  {v:+.6f}   (polled {polled:3d}, displayed {displayed:3d})")

    rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
        # Read at full poll rate — IOC sees every request.
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.do_action(on_next=on_polled),
        # sample: of all values arriving within each display_ms window,
        # emit only the most recent one and discard the rest.
        # One operator replaces: synchronized flag, manual drop counter, sleep loop.
        ops.sample(timedelta(milliseconds=display_ms), scheduler=scheduler),
        ops.do_action(on_next=on_displayed),
    ).subscribe(
        on_next=lambda _: None,  # printing done in do_action
        on_error=lambda e: print(f"ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

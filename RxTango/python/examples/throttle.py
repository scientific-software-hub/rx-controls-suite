"""Rate-limit a fast polling stream using ops.sample.

Polls double_scalar at a high frequency but only passes the most recent
value downstream every N seconds — decoupling producer rate from consumer rate.

Mirrors `TangoTestThrottle.java` (`throttleLast` → `sample` in RxPY).

Usage:
    python throttle.py [device] [poll-ms] [sample-ms]

    device     defaults to tango://localhost:10000/sys/tg_test/1
    poll-ms    poll interval; defaults to 100 (10 Hz)
    sample-ms  output interval; defaults to 1000 (1 Hz)
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute


async def main() -> None:
    device    = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    poll_ms   = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    sample_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print(
        f"Throttle demo — poll={poll_ms} ms, emit latest every {sample_ms} ms "
        f"(Ctrl+C to stop)\n"
    )
    print(f"  {'sampled value':>20}")
    print("  " + "-" * 22)

    rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
        ops.sample(timedelta(milliseconds=sample_ms), scheduler=scheduler),
    ).subscribe(
        on_next=lambda v: print(f"  {v:>+20.6f}"),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

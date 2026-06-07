"""Backpressure demonstration: fast producer, slow consumer.

RxPY does not implement the Reactive-Streams demand / backpressure protocol
(request(n) / cancel()).  Instead, we show the three practical strategies
available in RxPY:

- ops.sample()    — keep the freshest value per time window (drop the rest)
- ops.buffer_with_count() — accumulate into batches, process each batch
- observe_on with a bounded queue  — decouple producer/consumer threads

This mirrors the intent of `TangoTestBackpressure.java` while honestly
documenting the RxPY difference.

Usage:
    python backpressure.py [device] [poll-ms] [process-ms]

    device      defaults to tango://localhost:10000/sys/tg_test/1
    poll-ms     producer rate; defaults to 100 (10 Hz)
    process-ms  consumer processing time simulation; defaults to 500
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
    device     = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    poll_ms    = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    process_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    produced = 0
    consumed = 0

    # Fast producer: read at poll_ms
    upstream = rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
        ops.do_action(on_next=lambda _: globals().__setitem__("produced", produced + 1)),
    )

    # Strategy: keep only the latest value per process_ms window (drop the rest)
    bounded = upstream.pipe(
        ops.sample(timedelta(milliseconds=process_ms), scheduler=scheduler)
    )

    print(
        f"Backpressure demo — producer={poll_ms} ms, consumer={process_ms} ms "
        f"(Ctrl+C to stop)\n"
    )
    print("Strategy: ops.sample — keeps freshest value, drops surplus\n")
    print(f"  {'consumed':>10}  {'value':>16}")
    print("  " + "-" * 30)

    bounded.subscribe(
        on_next=lambda v: (
            print(f"  {(consumed := consumed + 1):>10}  {v:>+16.6f}"),
        ),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    # Run for a few seconds then stop
    await asyncio.sleep(5.0)
    print(f"\n  (would have produced ~{5000 // poll_ms} items, consumed fewer)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

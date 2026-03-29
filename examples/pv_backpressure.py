"""Demonstrates backpressure: a fast producer meeting a slow consumer.

The producer polls TEST:CALC at 100 ms (10 Hz).
The consumer takes 600 ms per item — 6x slower than the producer.

Three strategies:

  latest (default) — sample the stream at the consumer rate, always getting
                     the freshest available value. The consumer never sees
                     stale queued readings.

  drop             — use a bounded asyncio.Queue. New values are dropped when
                     the queue is full. Consumer drains at its own pace.

  buffer           — queue up to N values, then crash when full.
                     Run this to see the overflow error.

Usage:
    python pv_backpressure.py <pv_name> [poll-ms] [process-ms] [--strategy latest|drop|buffer] [--buffer-size N]

Examples:
    python pv_backpressure.py TEST:CALC
    python pv_backpressure.py TEST:CALC 100 600 --strategy drop
    python pv_backpressure.py TEST:CALC 100 600 --strategy buffer --buffer-size 5
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
        print(
            "Usage: pv_backpressure.py <pv_name> [poll-ms=100] [process-ms=600] "
            "[--strategy latest|drop|buffer] [--buffer-size N]",
            file=sys.stderr,
        )
        sys.exit(1)

    pv_name = sys.argv[1]
    poll_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    process_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 600

    strategy = "latest"
    buf_size = 8
    i = 4
    while i < len(sys.argv):
        if sys.argv[i] == "--strategy" and i + 1 < len(sys.argv):
            strategy = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--buffer-size" and i + 1 < len(sys.argv):
            buf_size = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    print(
        f"Producer: poll every {poll_ms} ms  |  Consumer: {process_ms} ms/item  |  Strategy: {strategy}"
    )
    print(f"Producer is {process_ms / poll_ms:.1f}x faster than consumer — Ctrl+C to stop\n")
    print(f"  {'prod':>5}  {'cons':>5}  {'skip':>6}  value")
    print("  " + "-" * 44)

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    produced = 0
    consumed = 0

    def on_produced(_: float) -> None:
        nonlocal produced
        produced += 1

    # Fast producer: read at poll rate.
    upstream = rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.do_action(on_next=on_produced),
    )

    if strategy == "latest":
        # sample at the consumer rate: always delivers the most recent value.
        # The consumer never wakes up to stale queued data.
        source = upstream.pipe(
            ops.sample(timedelta(milliseconds=process_ms), scheduler=scheduler)
        )

        async def consume(v: float) -> None:
            nonlocal consumed
            consumed += 1
            print(f"  {produced:5d}  {consumed:5d}  {produced - consumed:6d}  {v:+.6f}")
            await asyncio.sleep(process_ms / 1000)

        source.subscribe(
            on_next=lambda v: asyncio.ensure_future(consume(v)),
            on_error=lambda e: print(f"\nERROR: {e}", file=sys.stderr),
            scheduler=scheduler,
        )

    elif strategy == "drop":
        # asyncio.Queue(1): if the consumer slot is occupied, new values are dropped.
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)

        upstream.subscribe(
            on_next=lambda v: queue.put_nowait(v) if not queue.full() else None,
            on_error=lambda e: print(f"\nERROR: {e}", file=sys.stderr),
            scheduler=scheduler,
        )

        async def drain() -> None:
            nonlocal consumed
            while True:
                v = await queue.get()
                consumed += 1
                print(f"  {produced:5d}  {consumed:5d}  {produced - consumed:6d}  {v:+.6f}")
                await asyncio.sleep(process_ms / 1000)

        asyncio.ensure_future(drain())

    elif strategy == "buffer":
        # asyncio.Queue(buf_size): raise if full.
        queue: asyncio.Queue = asyncio.Queue(maxsize=buf_size)

        def enqueue(v: float) -> None:
            try:
                queue.put_nowait(v)
            except asyncio.QueueFull:
                raise OverflowError(
                    f"Buffer full ({buf_size} items). Producer too fast for consumer."
                )

        upstream.subscribe(
            on_next=enqueue,
            on_error=lambda e: print(f"\nERROR ({type(e).__name__}): {e}", file=sys.stderr),
            scheduler=scheduler,
        )

        async def drain() -> None:
            nonlocal consumed
            while True:
                v = await queue.get()
                consumed += 1
                print(f"  {produced:5d}  {consumed:5d}  {produced - consumed:6d}  {v:+.6f}")
                await asyncio.sleep(process_ms / 1000)

        asyncio.ensure_future(drain())

    else:
        print(f"Unknown strategy: {strategy}", file=sys.stderr)
        sys.exit(1)

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

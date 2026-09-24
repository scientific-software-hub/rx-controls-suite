"""Time-windowed zip: pair up two attributes sampled in the same window,
reporting the measured timestamp skew of each pair.

Uses ops.buffer_with_count + rx.zip to collect bursts from two fast-polled
streams and pair samples by position within the window — this pairs by
*count*, not by time, so "window N" from each stream can still be
measurably apart; correlate_snapshot's single-pair skew doesn't apply
directly to a pair of buffered lists, so each pair's skew is computed
the same way, by index, once both windows have filled.

Mirrors `TangoTestZipWindow.java`.

Usage:
    python zip_window.py [device] [window] [interval-ms]

    device       defaults to tango://localhost:10000/sys/tg_test/1
    window       samples per window; defaults to 5
    interval-ms  sample rate; defaults to 200
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute_ts


async def main() -> None:
    device      = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    window      = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    interval_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    period = timedelta(milliseconds=interval_ms)

    def make_buffered(attr: str) -> rx.Observable:
        # concat_map (not flat_map/exhaust): a window buffer must not lose a
        # sample — a dropped tick would corrupt the window.
        return rx.interval(period, scheduler=scheduler).pipe(
            ops.concat_map(lambda _: read_attribute_ts(device, attr)),
            ops.buffer_with_count(count=window, skip=window),  # non-overlapping
        )

    print(f"Time-windowed zip (window={window}) on {device}  (Ctrl+C to stop)\n")

    rx.zip(
        make_buffered("double_scalar"),
        make_buffered("long_scalar"),
    ).pipe(
        # Pair by position within the window; report each pair's value and
        # its measured skew — "window N from each stream" is a count-based
        # pairing, not a time-based one, so the two samples at position i
        # can still be measurably apart.
        ops.map(lambda pair: [
            (a.value, b.value, abs(a.ts - b.ts))
            for a, b in zip(pair[0], pair[1])
        ]),
    ).subscribe(
        on_next=lambda rows: print("\n".join(
            f"  double={r[0]:+.2f}  long={r[1]}  skew={r[2]:.4f}s" for r in rows
        ) + "\n"),
        on_error=lambda e: print(f"  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

"""Cross-system beam-line normalization: Tango Controls + EPICS Channel Access.

Scenario
--------
A detector count rate arrives as an EPICS PV (TEST:CALC).
A beam current monitor is exposed as a Tango device attribute (double_scalar).
We compute normalized intensity = detector_counts / |beam_current| on every
tick and write the result back to EPICS (TEST:DOUBLE).

The same ReactiveX operator vocabulary — zip, map, concat_map, interval —
works identically across both control systems.

  Tango   sys/tg_test/1  double_scalar  →─┐
                                           ├─ correlate → normalize → write EPICS TEST:DOUBLE
  EPICS   TEST:CALC                     →─┘

correlate_snapshot (built on rx.zip) is used instead of a bare zip: it
reports the measured skew between the Tango attribute's own
DeviceAttribute.time and the EPICS PV's own CA timestamp, since "both
reads completed" says nothing on its own about whether the two values
describe the same instant — the whole point of this demo is that they
come from two independent control systems with no shared clock.

Demo A (runs once):
    Cross-system snapshot via correlate_snapshot — both reads fire in
    parallel, the pair is only emitted when BOTH complete, and the
    measured timestamp skew is reported alongside the values.

Demo B (runs until Ctrl+C):
    Continuous pipeline — poll at <interval-ms>, normalize, write result.

Usage
-----
    python examples/tango_epics_normalize.py [tango-device] [interval-ms]

    tango-device  defaults to tango://localhost:10000/sys/tg_test/1
    interval-ms   defaults to 1000

Prerequisites
-------------
    uv pip install -e RxTango/python -e RxEpics/python
    docker compose -f RxTango/java/docker-compose.yml up -d   # Tango stack
    docker compose -f RxEpics/python/docker-compose.yml up -d # EPICS soft IOC

See also
--------
    demo/synchrotron-beamline/guarded_scan.py — a comprehensive combined demo
    that fuses a C++ storage-ring simulator (Tango) with a tomography beamline
    (EPICS): beam-loss recovery, orbit-quality flags, vacuum-burst abort, and
    backpressure — all in one declarative reactive pipeline.
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "RxEpics" / "python" / "src"))
sys.path.insert(0, str(ROOT / "RxTango" / "python" / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv_ts
from rxepics.channel_write import write_pv
from rxepics.correlate import correlate_snapshot  # duck-typed on Reading; works for
                                                    # either package's Reading objects
from rxtango import read_attribute, read_attribute_ts  # formerly the inline read_tango_attr helper


def poll_tango_attr(device: str, attribute: str, interval_ms: int, scheduler) -> rx.Observable:
    """Interval-polled Tango attribute via rxtango.read_attribute.

    map + exclusive() (RxPY has no exhaust_map), not flat_map: display poll
    — only the freshest value matters, a skipped tick under load is
    harmless.
    """
    return rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.map(lambda _: read_attribute(device, attribute)),
        ops.exclusive(),
    )


# ── main ──────────────────────────────────────────────────────────────────────

TANGO_ATTR  = "double_scalar"
EPICS_READ  = "TEST:CALC"
EPICS_WRITE = "TEST:DOUBLE"


async def demo_a_snapshot(device: str, ctx: Context, scheduler) -> None:
    """Demo A — one-shot cross-system snapshot.

    correlate_snapshot fires both reads in parallel and emits a single
    pair once BOTH complete — same guarantee as a bare rx.zip.  If either
    fails, the error propagates immediately.  It additionally reports the
    measured gap between the Tango attribute's own timestamp and the
    EPICS PV's own timestamp: the two control systems share no clock, so
    "both completed" is not "the same instant".
    """
    print("\n── Demo A: cross-system snapshot (one shot) ──────────────────────")
    print(f"  Tango  {device}/{TANGO_ATTR}")
    print(f"  EPICS  {EPICS_READ}")

    done = asyncio.Event()

    correlate_snapshot(
        read_attribute_ts(device, TANGO_ATTR),
        read_pv_ts(EPICS_READ, ctx),
    ).subscribe(
        on_next=lambda c: print(
            f"\n  beam_current  = {c.values[0]:+.4f}  (Tango)\n"
            f"  detector      = {c.values[1]:+.4f}  (EPICS)\n"
            f"  normalized    = {c.values[1] / max(abs(c.values[0]), 1e-9):+.6f}\n"
            f"  skew          = {c.skew:.4f}s"
        ),
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


async def demo_b_pipeline(
    device: str,
    ctx: Context,
    scheduler,
    interval_ms: int,
) -> None:
    """Demo B — continuous cross-system normalize-and-store pipeline.

    Every tick:
      1. Read  Tango   double_scalar   (beam current)
      2. Read  EPICS   TEST:CALC       (raw detector counts)  — in parallel via correlate_snapshot
      3. Map   normalize: counts / |current|
      4. Write EPICS   TEST:DOUBLE     (normalized intensity)
      5. Print confirmation, including the measured cross-system skew

    No threads. No locks. No callbacks.
    """
    print("\n── Demo B: continuous cross-system pipeline (Ctrl+C to stop) ────")
    print(f"  {device}/{TANGO_ATTR}  ×  {EPICS_READ}  →  {EPICS_WRITE}")
    print(f"  interval: {interval_ms} ms\n")
    print(f"  {'beam_current':>14}  {'detector':>12}  {'normalized':>14}  {'skew (s)':>10}  written")
    print("  " + "-" * 70)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(

        # Step 1+2: read both systems in parallel on every tick via
        # correlate_snapshot — same guarantee as a bare rx.zip, plus the
        # measured skew between the Tango attribute's and the EPICS PV's
        # own timestamps (the two systems share no clock).
        # concat_map (not flat_map): each tick's pair is serialized, so
        # ticks stay in order under load.
        ops.concat_map(
            lambda _: correlate_snapshot(
                read_attribute_ts(device, TANGO_ATTR),
                read_pv_ts(EPICS_READ, ctx),
            )
        ),

        # Step 3: normalize — guard against near-zero beam current
        ops.map(lambda c: (c.values[0], c.values[1], c.values[1] / max(abs(c.values[0]), 1e-9), c.skew)),

        ops.do_action(on_next=lambda t: print(
            f"  {t[0]:>+14.4f}  {t[1]:>+12.4f}  {t[2]:>+14.6f}  {t[3]:>10.4f}", end="  "
        )),

        # Step 4: write normalized value to EPICS. concat_map (not
        # flat_map): a write must not race the next tick's write.
        ops.concat_map(lambda t: write_pv(EPICS_WRITE, t[2], ctx)),

    ).subscribe(
        on_next=lambda v: print(f"→ {EPICS_WRITE} = {v:.6f}"),
        on_error=lambda e: print(f"\n  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


async def main() -> None:
    device     = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"
    interval_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx       = Context()

    await demo_a_snapshot(device, ctx, scheduler)
    await demo_b_pipeline(device, ctx, scheduler, interval_ms)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

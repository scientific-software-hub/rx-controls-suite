"""Cross-system beam-line normalization: Tango Controls + EPICS Channel Access.

Scenario
--------
A detector count rate arrives as an EPICS PV (TEST:CALC).
A beam current monitor is exposed as a Tango device attribute (double_scalar).
We compute normalized intensity = detector_counts / |beam_current| on every
tick and write the result back to EPICS (TEST:DOUBLE).

The same ReactiveX operator vocabulary — zip, map, flat_map, interval —
works identically across both control systems.

  Tango   sys/tg_test/1  double_scalar  →─┐
                                           ├─ zip → normalize → write EPICS TEST:DOUBLE
  EPICS   TEST:CALC                     →─┘

Demo A (runs once):
    Cross-system snapshot via rx.zip — both reads fire in parallel,
    the pair is only emitted when BOTH complete.

Demo B (runs until Ctrl+C):
    Continuous pipeline — poll at <interval-ms>, normalize, write result.

The thin read_tango_attr() / poll_tango_attr() helpers below follow the
exact same rx.create pattern as rxepics, and anticipate the future
RxTango/python sub-project.

Usage
-----
    python examples/tango_epics_normalize.py [tango-device] [interval-ms]

    tango-device  defaults to tango://localhost:10000/sys/tg_test/1
    interval-ms   defaults to 1000

Prerequisites
-------------
    pip install pytango caproto[asyncio] reactivex
    docker compose -f RxTango/java/docker-compose.yml up -d   # Tango stack
    docker compose -f RxEpics/python/docker-compose.yml up -d # EPICS soft IOC
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

# ── add rxepics to path ───────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "RxEpics" / "python" / "src"))

import tango                                      # PyTango
import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv

# ── thin Tango reactive wrappers ──────────────────────────────────────────────
# These mirror the rxepics API exactly: same rx.create pattern, same signature
# shape.  They will move to RxTango/python once that sub-project is created.

_proxy_cache: dict[str, tango.DeviceProxy] = {}


def _get_proxy(device: str) -> tango.DeviceProxy:
    if device not in _proxy_cache:
        _proxy_cache[device] = tango.DeviceProxy(device)
    return _proxy_cache[device]


def read_tango_attr(device: str, attribute: str) -> rx.Observable:
    """Single-shot Tango attribute read — mirrors rxepics.read_pv."""

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, _get_proxy, device)
                result = await loop.run_in_executor(None, proxy.read_attribute, attribute)
                observer.on_next(float(result.value))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)


def poll_tango_attr(
    device: str,
    attribute: str,
    interval_ms: int,
    scheduler,
) -> rx.Observable:
    """Interval-polled Tango attribute — mirrors the RxJTango pattern:
    Flowable.interval(...).flatMapSingle(read_attr).
    """
    return rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_tango_attr(device, attribute))
    )


# ── main ──────────────────────────────────────────────────────────────────────

TANGO_ATTR  = "double_scalar"
EPICS_READ  = "TEST:CALC"
EPICS_WRITE = "TEST:DOUBLE"


async def demo_a_snapshot(device: str, ctx: Context, scheduler) -> None:
    """Demo A — one-shot cross-system snapshot.

    rx.zip fires both reads in parallel and emits a single pair once
    BOTH complete.  If either fails, the error propagates immediately.
    """
    print("\n── Demo A: cross-system snapshot (one shot) ──────────────────────")
    print(f"  Tango  {device}/{TANGO_ATTR}")
    print(f"  EPICS  {EPICS_READ}")

    done = asyncio.Event()

    rx.zip(
        read_tango_attr(device, TANGO_ATTR),
        read_pv(EPICS_READ, ctx),
    ).subscribe(
        on_next=lambda pair: print(
            f"\n  beam_current  = {pair[0]:+.4f}  (Tango)\n"
            f"  detector      = {pair[1]:+.4f}  (EPICS)\n"
            f"  normalized    = {pair[1] / max(abs(pair[0]), 1e-9):+.6f}"
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
      2. Read  EPICS   TEST:CALC       (raw detector counts)  — in parallel via zip
      3. Map   normalize: counts / |current|
      4. Write EPICS   TEST:DOUBLE     (normalized intensity)
      5. Print confirmation

    No threads. No locks. No callbacks.
    """
    print("\n── Demo B: continuous cross-system pipeline (Ctrl+C to stop) ────")
    print(f"  {device}/{TANGO_ATTR}  ×  {EPICS_READ}  →  {EPICS_WRITE}")
    print(f"  interval: {interval_ms} ms\n")
    print(f"  {'beam_current':>14}  {'detector':>12}  {'normalized':>14}  written")
    print("  " + "-" * 58)

    rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(

        # Step 1+2: read both systems in parallel on every tick
        ops.flat_map(
            lambda _: rx.zip(
                read_tango_attr(device, TANGO_ATTR),
                read_pv(EPICS_READ, ctx),
            )
        ),

        # Step 3: normalize — guard against near-zero beam current
        ops.map(lambda pair: (pair[0], pair[1], pair[1] / max(abs(pair[0]), 1e-9))),

        ops.do_action(on_next=lambda t: print(
            f"  {t[0]:>+14.4f}  {t[1]:>+12.4f}  {t[2]:>+14.6f}", end="  "
        )),

        # Step 4: write normalized value to EPICS
        ops.flat_map(lambda t: write_pv(EPICS_WRITE, t[2], ctx)),

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

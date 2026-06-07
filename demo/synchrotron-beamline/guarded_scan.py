"""Guarded Tomography Scan — Storage Ring × Beamline.

One Python process. Two control systems. One declarative pipeline.

The storage ring state is read directly from Tango (rxtango). It drives:

  • Beam-loss recovery   — each projection waits for healthy beam before
                           starting; the shutter closes and re-opens
                           automatically via distinct_until_changed.

  • Orbit-drift flagging — every frame is tagged with a quality flag
                           derived from the Tango orbit-X reading.
                           No polling loop. A single rx.zip across both
                           EPICS and Tango at acquisition time.

  • Vacuum-burst abort   — an interlock alarm stream feeds take_until.
                           The scan terminates cleanly, status=ABORTED.

  • Backpressure         — share() splits the frame stream into two
                           branches: HDF5 (every frame) and live display
                           (sampled at display_ms). One operator handles
                           the overload policy.

Architecture
------------

  ring_health (shared, 1 Hz Tango poll) ──────────────────────────────────┐
                                                                            │
    ┌─ shutter supervisor (distinct_until_changed on beam_ok → write PV)   │
    │                                                                        │
    └─ abort_trigger    (filter interlocks>0, take(1) → take_until)        │
                                                                            │
  scan = rx.concat(                                                         │
    setup writes,                                                           │
    [wait_healthy → acquire_projection] × N,   ← gated on ring state       │
    teardown_done                                                           │
  ).pipe(take_until(abort_trigger))                                        │
                                                                            │
  source = scan.pipe(share())                                               │
    ├─ HDF5 writer      (every frame)                                       │
    ├─ live display     (sample(display_ms))                                │
    └─ completion       (scan_done.set())                                   │

Each frame: (ts, index, angle, counts, beam_posx, beam_posy,
             ring_current[Tango], orbit_x[Tango], quality_ok)

Usage
-----
    python guarded_scan.py [--projections N] [--exposure-ms MS]
                           [--display-ms MS] [--motor-speed DEG/S]
                           [--ascii]

Prerequisites
-------------
    docker compose up -d --build

    # In a second terminal — try these during a running scan:
    python inject_fault.py beam_loss      # scan pauses, shutter closes
    python inject_fault.py nominal        # scan resumes, shutter opens
    python inject_fault.py orbit_drift    # frames flagged low-quality
    python inject_fault.py vacuum_burst   # emergency abort
"""

import argparse
import asyncio
import shutil
import sys
import time
from datetime import timedelta
from pathlib import Path

import h5py
import numpy as np
import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context
from reactivex.scheduler.eventloop import AsyncIOScheduler

from facility import (
    CONTROLLER, SECTOR_04,
    MIN_BEAM_CURRENT, ORBIT_ALARM, SCAN_RUNNING, SCAN_DONE, SCAN_ABORTED,
    PV_ROT_VAL, PV_ROT_MOVN, PV_ROT_SPEED,
    PV_DET_ACQUIRE, PV_DET_COUNTS, PV_DET_ACQUIRING, PV_DET_EXPOSURE,
    PV_BEAM_POSX, PV_BEAM_POSY,
    PV_SHUTTER, PV_SCAN_STATUS, PV_SCAN_CUR_ANGLE, PV_SCAN_CUR_PROJ,
    Health, is_healthy, ring_health, poll_until,
)

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv
from rxtango import read_attribute


# ── Cross-system projection acquisition ───────────────────────────────────────

def guarded_acquire_projection(
    angle: float,
    index: int,
    ctx: Context,
    health: rx.Observable,
    scheduler,
) -> rx.Observable:
    """One projection, gated by ring health, tagged with cross-system quality.

    Returns a cold Observable that emits exactly one frame tuple:

        (timestamp, index, angle, counts,
         beam_posx[EPICS], beam_posy[EPICS],
         ring_current[Tango], orbit_x[Tango], quality_ok)

    Step 0  — gate: wait until the ring is healthy before moving the motor.
    Steps 1–5 — standard tomography acquisition pipeline (motor → detector).
    Step 6  — cross-system zip: EPICS counts + position + Tango ring state.
    Step 7  — tag the frame with the quality flag from the orbit reading.
    Step 8  — update scan-state PVs (pass frame through).

    The gate is the key: the scan never starts a projection into a bad beam.
    The cross-system zip is the showstopper: one rx.zip, two control systems,
    fired in parallel, completed atomically.
    """

    # ── Step 0: wait until ring is healthy ────────────────────────────────────
    # filter(is_healthy) blocks until the next healthy emission.
    # take(1) completes after the first match.
    # ignore_elements() discards the Health value — we only need the timing.
    wait_healthy = health.pipe(
        ops.filter(is_healthy),
        ops.take(1),
        ops.do_action(on_next=lambda _: print(
            f"  [proj {index:3d}] beam OK — starting at {angle:.2f}°"
        )),
        ops.ignore_elements(),
    )

    # ── Steps 1–8: full acquisition pipeline ──────────────────────────────────
    acquire = (
        # Step 1: move motor to target angle
        write_pv(PV_ROT_VAL, angle, ctx)
        .pipe(
            # Step 2: wait for motor to stop (MOVN == 0)
            ops.flat_map(lambda _: poll_until(
                PV_ROT_MOVN, lambda v: v == 0, 10, ctx, scheduler,
            )),
            # Step 3: trigger detector
            ops.flat_map(lambda _: write_pv(PV_DET_ACQUIRE, 1, ctx)),
            # Step 4: wait for acquisition to start
            ops.flat_map(lambda _: poll_until(
                PV_DET_ACQUIRING, lambda v: v == 1, 5, ctx, scheduler,
            )),
            # Step 5: wait for acquisition to complete
            ops.flat_map(lambda _: poll_until(
                PV_DET_ACQUIRING, lambda v: v == 0, 5, ctx, scheduler,
            )),
            # Step 6: cross-system zip — EPICS counts + Tango ring state
            #
            # This is the showstopper: one rx.zip fires reads against
            # two different control systems simultaneously:
            #   • caproto Channel Access → EPICS soft IOC (3 PVs)
            #   • PyTango DeviceProxy    → C++ cppTango server (2 attributes)
            # All five requests are in-flight at the same time.
            # The tuple is only emitted when ALL five complete.
            ops.flat_map(lambda _: rx.zip(
                read_pv(PV_DET_COUNTS,  ctx),          # EPICS
                read_pv(PV_BEAM_POSX,   ctx),          # EPICS
                read_pv(PV_BEAM_POSY,   ctx),          # EPICS
                read_attribute(CONTROLLER, "BeamCurrent"),  # Tango
                read_attribute(SECTOR_04,  "OrbitX"),       # Tango
            )),
            # Step 7: assemble frame — tag with quality derived from orbit
            ops.map(lambda r: (
                time.time(),     # 0  timestamp
                index,           # 1  projection index
                angle,           # 2  angle [deg]
                float(r[0]),     # 3  counts  [EPICS]
                float(r[1]),     # 4  beam_posx [mm, EPICS]
                float(r[2]),     # 5  beam_posy [mm, EPICS]
                float(r[3]),     # 6  ring_current [mA, Tango]
                float(r[4]),     # 7  orbit_x [µm, Tango]
                abs(float(r[4])) < ORBIT_ALARM,  # 8  quality_ok
            )),
            # Step 8: update scan-state PVs (pass frame through)
            ops.flat_map(lambda frame: rx.zip(
                write_pv(PV_SCAN_CUR_ANGLE, frame[2], ctx),
                write_pv(PV_SCAN_CUR_PROJ,  frame[1], ctx),
            ).pipe(ops.map(lambda _: frame))),
        )
    )

    # Sequence: wait for healthy ring → then acquire
    return rx.concat(wait_healthy, acquire)


# ── Scan composition ──────────────────────────────────────────────────────────

def guarded_scan(
    ctx: Context,
    health: rx.Observable,
    num_proj: int = 36,
    start_angle: float = 0.0,
    stop_angle: float = 180.0,
    exposure_ms: float = 30.0,
    motor_speed: float = 10.0,
    scheduler=None,
    abort_trigger: rx.Observable = None,
) -> rx.Observable:
    """Build the guarded tomography scan Observable.

    Identical in structure to tomography_scan() in the EPICS demo, but:
      • Each projection is wrapped in a health gate (wait_healthy).
      • The cross-system zip reads from both EPICS and Tango per frame.
      • take_until(abort_trigger) terminates on interlock alarm.

    Returns a cold, concat-ed Observable.
    """
    angles = [
        start_angle + i * (stop_angle - start_angle) / max(num_proj - 1, 1)
        for i in range(num_proj)
    ]

    projections = [
        guarded_acquire_projection(angle, i, ctx, health, scheduler)
        for i, angle in enumerate(angles)
    ]

    scan = rx.concat(
        # setup
        write_pv(PV_ROT_SPEED,   motor_speed, ctx).pipe(
            ops.flat_map(lambda _: write_pv(PV_DET_EXPOSURE, exposure_ms, ctx)),
            ops.flat_map(lambda _: write_pv(PV_SCAN_STATUS,  SCAN_RUNNING, ctx)),
            ops.flat_map(lambda _: write_pv(PV_SHUTTER,      1,            ctx)),
            ops.ignore_elements(),
        ),
        # projections
        *projections,
        # teardown — only reached on natural completion
        write_pv(PV_SCAN_STATUS, SCAN_DONE, ctx).pipe(ops.ignore_elements()),
    )

    if abort_trigger is not None:
        scan = scan.pipe(ops.take_until(abort_trigger))

    return scan


# ── Live display (guarded version) ────────────────────────────────────────────

_SAMPLE_FRAMES = ["[|]", "[/]", "[-]", "[\\]", "[|]", "[/]", "[-]", "[\\]"]


def _sample_art(angle_deg: float) -> str:
    idx = int((angle_deg % 180) / 180 * len(_SAMPLE_FRAMES)) % len(_SAMPLE_FRAMES)
    return _SAMPLE_FRAMES[idx]


class GuardedLiveDisplay:
    """ASCII animation showing both beamline and ring state per frame."""

    def __init__(self, num_proj: int, display_ms: float):
        self.num_proj = num_proj
        self.display_ms = display_ms
        self._lines = 0

    def __call__(self, frame: tuple) -> None:
        self._render(frame)

    def _render(self, frame: tuple) -> None:
        ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality = frame
        pct = min((i + 1) / self.num_proj * 100, 100)
        w   = min(shutil.get_terminal_size().columns, 80) - 2

        bar_w  = w - 10
        filled = int(bar_w * (i + 1) / self.num_proj)
        bar    = "[" + "#" * filled + " " * (bar_w - filled) + "]"

        sample = _sample_art(angle)
        quality_icon  = "\033[32m✓ good\033[0m" if quality else "\033[33m~ drift\033[0m"
        orbit_str     = f"{orbit_x:+.1f} µm  {quality_icon}"

        lines = [
            f"  \033[1mGuarded Tomography Scan\033[0m  {pct:5.1f}%",
            f"  \033[36m" + "─" * (w + 2) + "\033[0m",
            f"  \033[33m☹\033[0m  \033[33m~~~\033[0m  {sample}  \033[33m~~~\033[0m  \033[32m▓▓\033[0m",
            f"  Ring→Beamline       Sample        Detector",
            f"  \033[34m{ring_cur:6.1f} mA\033[0m  "
            f"    {angle:6.1f}°    {counts:8.0f} cts",
            f"  orbit: {orbit_str:<36s}",
            f"  beam pos: ({bpx:+.4f}, {bpy:+.4f}) mm",
            "",
            f"  {bar}",
            f"  {i+1} / {self.num_proj} frames",
            "",
            f"  \033[2mHDF5: every frame | Display: {1000/self.display_ms:.0f} Hz"
            f" | sample() drops the rest | quality from Tango orbit\033[0m",
        ]

        output = "\n".join(lines)
        if self._lines > 0:
            output = f"\033[{self._lines}A" + output
        self._lines = len(lines)
        print(output, flush=True)

    def cleanup(self) -> None:
        print()
        print()


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    p = argparse.ArgumentParser(description="Guarded scan — Storage Ring × Beamline")
    p.add_argument("--projections",  type=int,   default=36)
    p.add_argument("--exposure-ms",  type=float, default=30.0)
    p.add_argument("--display-ms",   type=float, default=250.0)
    p.add_argument("--motor-speed",  type=float, default=10.0,
                   help="Motor speed in deg/s")
    p.add_argument("--ascii",        action="store_true",
                   help="Rich ASCII animation instead of table rows")
    args = p.parse_args()

    num_proj    = args.projections
    exposure_ms = args.exposure_ms
    display_ms  = args.display_ms
    motor_speed = args.motor_speed

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx       = Context()

    out_dir  = Path(__file__).resolve().parent
    h5_path  = out_dir / f"scan_{time.strftime('%Y%m%d_%H%M%S')}.h5"

    angle_step   = 180.0 / max(num_proj - 1, 1)
    est_motor_ms = (angle_step / motor_speed) * 1000
    est_frame_ms = est_motor_ms + exposure_ms
    est_fps      = 1000.0 / est_frame_ms if est_frame_ms > 0 else float("inf")
    drop_pct     = max(0.0, (1.0 - est_frame_ms / display_ms) * 100)

    print()
    print("  Guarded Tomography Scan — Storage Ring × Beamline")
    print("  " + "=" * 62)
    print(f"  Projections: {num_proj}  |  Exposure: {exposure_ms:.0f} ms"
          f"  |  Display: {display_ms:.0f} ms")
    print(f"  Motor speed: {motor_speed:.0f} deg/s"
          f"  |  Est. fps: {est_fps:.1f}  |  Drop rate: {drop_pct:.0f}%")
    print()
    print("  Ring health gates:  beam-loss → pause  |  vacuum-burst → abort")
    print("  Quality flag:       derived from Tango OrbitX per frame")
    print("  " + "=" * 62)
    print(f"  HDF5: {h5_path}")
    print()
    print("  Inject faults in a second terminal:")
    print("    python inject_fault.py beam_loss      # pause + shutter close")
    print("    python inject_fault.py nominal        # resume + shutter open")
    print("    python inject_fault.py orbit_drift    # quality flags appear")
    print("    python inject_fault.py vacuum_burst   # emergency abort")
    print()

    # ── HDF5 setup ────────────────────────────────────────────────────────────
    f  = h5py.File(h5_path, "w")
    ds = f.create_dataset(
        "projections",
        shape=(num_proj,),
        dtype=np.dtype([
            ("timestamp",    "f8"),
            ("proj_index",   "i4"),
            ("angle",        "f4"),
            ("counts",       "f8"),
            ("beam_posx",    "f4"),
            ("beam_posy",    "f4"),
            ("ring_current", "f4"),   # from Tango
            ("orbit_x",      "f4"),   # from Tango
            ("quality_ok",   "?"),    # derived from Tango orbit
        ]),
    )
    f.attrs["exposure_ms"]    = exposure_ms
    f.attrs["motor_speed"]    = motor_speed
    f.attrs["num_projections"] = num_proj

    # ── Counters / events ─────────────────────────────────────────────────────
    hdf5_written  = 0
    display_shown = 0
    scan_aborted  = asyncio.Event()
    scan_done     = asyncio.Event()
    start_time    = 0.0

    # ── 1. Build shared ring-health stream ────────────────────────────────────
    # All downstream operators subscribe to this one polling source.
    health = ring_health(scheduler, interval_ms=1000)

    # ── 2. Abort trigger: fires once when an interlock appears ─────────────────
    # take_until(abort_trigger) on the scan terminates the pipeline cleanly.
    def _on_abort(h: Health) -> None:
        scan_aborted.set()
        print(f"\n  ⚠  VACUUM BURST: interlocks={h.interlocks} — emergency abort!")

    abort_trigger = health.pipe(
        ops.filter(lambda h: h.interlocks > 0),
        ops.take(1),
        ops.do_action(on_next=_on_abort),
    )

    # ── 3. Shutter supervisor ─────────────────────────────────────────────────
    # Three operators: map → distinct_until_changed → flat_map(write_pv).
    # When beam drops: close shutter. When it recovers: open shutter.
    # distinct_until_changed ensures we only write on state *transitions*.
    supervisor_disp = health.pipe(
        ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),
        ops.distinct_until_changed(),
        ops.flat_map(
            lambda ok: write_pv(PV_SHUTTER, 1 if ok else 0, ctx)
        ),
    ).subscribe(
        on_next=lambda v: print(
            f"  {'🔆 Shutter OPENED' if v else '🔒 Shutter CLOSED'}"
            f"  (beam {'OK' if v else 'lost — scan paused'})"
        ),
        on_error=lambda e: print(f"  supervisor error: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    # ── 4. Build shared scan source ───────────────────────────────────────────
    source = guarded_scan(
        ctx,
        health,
        num_proj=num_proj,
        start_angle=0.0,
        stop_angle=180.0,
        exposure_ms=exposure_ms,
        motor_speed=motor_speed,
        scheduler=scheduler,
        abort_trigger=abort_trigger,
    ).pipe(ops.share())   # one execution, two consumers

    # ── 5a. HDF5 writer — keeps every frame ───────────────────────────────────
    def write_frame(frame: tuple) -> None:
        nonlocal hdf5_written
        ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality = frame
        ds[i] = (ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality)
        hdf5_written += 1

    source.subscribe(
        on_next=write_frame,
        on_error=lambda e: print(f"\n  HDF5 writer error: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    # ── 5b. Live display — throttled via sample() ─────────────────────────────
    live_disp: GuardedLiveDisplay | None = None

    if args.ascii:
        live_disp = GuardedLiveDisplay(num_proj, display_ms)

        def display_ascii(frame: tuple) -> None:
            nonlocal display_shown
            display_shown += 1
            live_disp(frame)

        display_handler = display_ascii
    else:
        print(f"  {'Frame':>5}  {'Angle':>7}  {'Counts':>8}  "
              f"{'Ring(mA)':>9}  {'OrbitX(µm)':>11}  "
              f"{'PosX':>8}  {'PosY':>8}  Q")
        print("  " + "-" * 78)

        def display_table(frame: tuple) -> None:
            nonlocal display_shown
            ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality = frame
            display_shown += 1
            q = "✓" if quality else "~"
            print(
                f"\r  {i+1:5d}  {angle:7.2f}  {counts:8.0f}  "
                f"{ring_cur:9.2f}  {orbit_x:+11.1f}  "
                f"{bpx:8.4f}  {bpy:8.4f}  {q}",
                end="", flush=True,
            )

        display_handler = display_table

    source.pipe(
        ops.sample(timedelta(milliseconds=display_ms), scheduler=scheduler),
    ).subscribe(
        on_next=display_handler,
        scheduler=scheduler,
    )

    # ── 5c. Completion handler ────────────────────────────────────────────────
    def on_completed() -> None:
        scan_done.set()

    def _sched_error(exc: Exception) -> None:
        async def _abort_teardown():
            try:
                pv, = await ctx.get_pvs(PV_SCAN_STATUS)
                await pv.write([SCAN_ABORTED])
                pv2, = await ctx.get_pvs(PV_SHUTTER)
                await pv2.write([0])
            except Exception:
                pass
        asyncio.ensure_future(_abort_teardown())
        print(f"\n  Scan error: {exc}", file=sys.stderr)
        scan_done.set()

    source.subscribe(
        on_next=lambda _: None,
        on_error=_sched_error,
        on_completed=on_completed,
        scheduler=scheduler,
    )

    # ── 5d. Capture start time from first frame ────────────────────────────────
    def capture_start(frame: tuple) -> None:
        nonlocal start_time
        if start_time == 0.0:
            start_time = frame[0]

    source.subscribe(on_next=capture_start, scheduler=scheduler)

    # ── Wait for scan to finish ────────────────────────────────────────────────
    await scan_done.wait()
    supervisor_disp.dispose()
    f.close()

    if live_disp is not None:
        live_disp.cleanup()
    elif not args.ascii:
        print()

    # ── Abort teardown ─────────────────────────────────────────────────────────
    if scan_aborted.is_set():
        print()
        print("  ── Emergency teardown ──────────────────────────────────────────")
        done = asyncio.Event()
        rx.zip(
            write_pv(PV_SCAN_STATUS, SCAN_ABORTED, ctx),
            write_pv(PV_SHUTTER, 0, ctx),
        ).subscribe(
            on_next=lambda _: print("  ✓ scan status = ABORTED | shutter CLOSED"),
            on_completed=done.set,
            scheduler=scheduler,
        )
        await done.wait()

    elapsed    = time.time() - start_time if start_time else 0
    actual_fps = hdf5_written / elapsed if elapsed > 0 else 0
    drop_actual = (
        (1.0 - display_shown / hdf5_written) * 100 if hdf5_written else 0
    )
    quality_pct = 0.0  # computed from HDF5 if needed

    w = min(shutil.get_terminal_size().columns, 78)
    print()
    print("  " + "=" * w)
    if scan_aborted.is_set():
        print("  Scan ABORTED (vacuum burst interlock).")
    else:
        print("  Scan complete.")
    print(f"  Frames acquired: {hdf5_written}"
          f"  |  Frames displayed: {display_shown}"
          f"  |  Drop: {drop_actual:.0f}%")
    print(f"  Elapsed: {elapsed:.2f}s  |  Fps: {actual_fps:.1f}")
    print(f"  HDF5: {h5_path}")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")

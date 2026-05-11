"""Tomography acquisition with HDF5 logging and throttled live display.

A tomography scan acquires projections at high rate. Two consumers share
the same data stream:

  1. HDF5 writer — stores every projection (must keep up)
  2. Live display — shows projections at human speed via sample()

The slow display consumer never backpressures the source — sample() drops
intermediate frames silently. One operator replaces queues, locks, flags,
and manual accounting.

Build: every step is a composed reactive pipeline. No imperative loops,
no async sleeps in the scan logic.

Usage:
    python tomography_scan.py [--projections 360] [--exposure-ms 30] [--display-ms 250]
"""

import argparse
import asyncio
import os
import shutil
import sys
import time
from datetime import timedelta
from pathlib import Path

# Allow running from any directory — point to the rxepics package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import h5py
import numpy as np
import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv


# -- reactive primitives -------------------------------------------------------

def poll_until(
    pv_name: str,
    predicate,
    period_ms: float,
    ctx: Context,
    scheduler,
) -> rx.Observable:
    """Poll *pv_name* every *period_ms* until *predicate(value)* is true.

    Emits the first matching value, then completes.  Built from three
    operators: interval → flat_map(read) → filter → take(1).
    """
    return rx.interval(timedelta(milliseconds=period_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.filter(predicate),
        ops.take(1),
    )


# -- projection pipeline -------------------------------------------------------

def acquire_projection(
    angle: float,
    index: int,
    ctx: Context,
    scheduler,
) -> rx.Observable:
    """Reactive pipeline for one tomography projection.

    Returns a single-shot Observable that emits one frame tuple:

        (timestamp, proj_index, angle, counts,
         beam_current, beam_posx, beam_posy)

    The pipeline:
      write motor target  →  wait for settle  →  trigger detector
      →  wait for exposure  →  zip(read results)  →  update scan PVs
      →  emit frame

    Every step is an Observable — no async/await, no sleep loops.
    """
    return (
        # -- move motor --
        write_pv("TOMO:ROT:VAL", angle, ctx)
        .pipe(
            # wait for motor to settle (MOVN == 0)
            ops.flat_map(lambda _: poll_until(
                "TOMO:ROT:MOVN", lambda v: v == 0, 10, ctx, scheduler,
            )),
        )
        # -- trigger detector --
        .pipe(
            ops.flat_map(lambda _: write_pv("TOMO:DET:ACQUIRE", 1, ctx)),
        )
        # -- wait for acquisition start --
        .pipe(
            ops.flat_map(lambda _: poll_until(
                "TOMO:DET:ACQUIRING", lambda v: v == 1, 5, ctx, scheduler,
            )),
        )
        # -- wait for acquisition complete --
        .pipe(
            ops.flat_map(lambda _: poll_until(
                "TOMO:DET:ACQUIRING", lambda v: v == 0, 5, ctx, scheduler,
            )),
        )
        # -- read detector + beam diagnostics concurrently --
        .pipe(
            ops.flat_map(lambda _: rx.zip(
                read_pv("TOMO:DET:COUNTS", ctx),
                read_pv("TOMO:BEAM:CURRENT", ctx),
                read_pv("TOMO:BEAM:POSX", ctx),
                read_pv("TOMO:BEAM:POSY", ctx),
            )),
        )
        # -- assemble frame tuple --
        .pipe(
            ops.map(lambda results: (
                time.time(), index, angle,
                results[0], results[1], results[2], results[3],
            )),
        )
        # -- update scan state PVs (pass frame through) --
        .pipe(
            ops.flat_map(lambda frame: rx.zip(
                write_pv("TOMO:SCAN:CUR_ANGLE", frame[2], ctx),
                write_pv("TOMO:SCAN:CUR_PROJ", frame[1], ctx),
            ).pipe(ops.map(lambda _: frame))),
        )
    )


# -- scan composition ----------------------------------------------------------

def tomography_scan(
    ctx: Context,
    num_proj: int = 360,
    start_angle: float = 0.0,
    stop_angle: float = 180.0,
    exposure_ms: float = 30.0,
    motor_speed: float = 10.0,
    scheduler=None,
) -> rx.Observable:
    """Return a cold Observable that runs a tomography scan.

    Composes the scan from three sections concatenated in order:

      setup writes  →  projection[0..N]  →  teardown write

    Each projection is itself a reactive pipeline.  The scan emits only
    frame tuples — setup/teardown values are suppressed via ignore_elements().
    """

    angles = [
        start_angle + i * (stop_angle - start_angle) / max(num_proj - 1, 1)
        for i in range(num_proj)
    ]

    projections = [
        acquire_projection(angle, i, ctx, scheduler)
        for i, angle in enumerate(angles)
    ]

    return rx.concat(
        # -- setup: configure devices, set scan status = RUNNING --
        write_pv("TOMO:ROT:SPEED", motor_speed, ctx).pipe(
            ops.flat_map(lambda _: write_pv("TOMO:DET:EXPOSURE", exposure_ms, ctx)),
            ops.flat_map(lambda _: write_pv("TOMO:SCAN:STATUS", 1, ctx)),
            ops.ignore_elements(),
        ),
        # -- the scan: each projection runs only after the previous completes --
        *projections,
        # -- teardown: set scan status = DONE --
        write_pv("TOMO:SCAN:STATUS", 2, ctx).pipe(ops.ignore_elements()),
    )


# -- live display (ASCII animation) -------------------------------------------

# Rotation frames for the sample — a rectangular block seen from 8 angles
# across 180 degrees of rotation.
# Sample visual: a line inside brackets rotates as the sample turns.
# [|] = face-on (beam through wide side), [-] = edge-on, [/] [\] = oblique.
_SAMPLE_FRAMES = [
    "[|]",   # 0°
    "[/]",   # 22°
    "[-]",   # 45°
    "[\\]",  # 67°  (single backslash in terminal: [\])
    "[|]",   # 90°
    "[/]",   # 112°
    "[-]",   # 135°
    "[\\]",  # 157°
]


def _sample_art(angle_deg: float) -> str:
    """Return the ASCII art for the sample at *angle_deg* (0–180)."""
    idx = int((angle_deg % 180) / 180 * len(_SAMPLE_FRAMES)) % len(_SAMPLE_FRAMES)
    return _SAMPLE_FRAMES[idx]


class LiveDisplay:
    """Multi-line ASCII animation of the tomography scan.

    Renders a beamline schematic with a rotating sample, progress bar,
    and live metrics.  Uses ANSI cursor-up sequences to overwrite the
    previous frame — no screen clearing, no flicker.

    Callable as an ``on_next`` callback for the sample() subscriber.
    """

    def __init__(self, num_proj: int, display_ms: float):
        self.num_proj = num_proj
        self.display_ms = display_ms
        self._lines = 0

    def __call__(self, frame: tuple) -> None:
        self._render(frame)

    def _render(self, frame: tuple) -> None:
        ts, i, angle, counts, beam_cur, beam_px, beam_py = frame
        pct = min((i + 1) / self.num_proj * 100, 100)
        w = min(shutil.get_terminal_size().columns, 80) - 2

        bar_w = w - 10
        filled = int(bar_w * (i + 1) / self.num_proj)
        bar = "[" + "#" * filled + " " * (bar_w - filled) + "]"

        sample = _sample_art(angle)
        pos_str = f"({beam_px:+.4f}, {beam_py:+.4f}) mm"

        lines = [
            f"  \033[1mTomography Scan\033[0m  {pct:5.1f}%",
            f"  \033[36m" + "─" * (w + 2) + "\033[0m",
            f"  \033[33m☹\033[0m  \033[33m~~~\033[0m  {sample}  \033[33m~~~\033[0m  \033[32m▓▓\033[0m",
            f"  Source     Sample        Detector",
            f"  {beam_cur:.1f} mA    {angle:6.1f}°       {counts:.0f} cts",
            "",
            f"  {bar}",
            f"  {i+1} / {self.num_proj} frames"
            f"     pos: {pos_str}",
            "",
            f"  \033[2mHDF5: every frame | Display: {1000/self.display_ms:.0f} Hz"
            f" | sample() drops the rest\033[0m",
        ]

        output = "\n".join(lines)

        if self._lines > 0:
            # Move cursor up to overwrite the previous render
            output = f"\033[{self._lines}A" + output

        self._lines = len(lines)
        print(output, flush=True)

    def cleanup(self) -> None:
        """Print final newline so the shell prompt lands below the display."""
        print()
        print()


# -- main ---------------------------------------------------------------------

async def main():
    p = argparse.ArgumentParser(description="Tomography scan — HDF5 + live display")
    p.add_argument("--projections", type=int, default=360)
    p.add_argument("--exposure-ms", type=float, default=30.0)
    p.add_argument("--display-ms", type=float, default=250.0)
    p.add_argument("--motor-speed", type=float, default=10.0,
                   help="Motor speed in deg/s (higher = faster scan)")
    p.add_argument("--ascii", action="store_true",
                   help="Rich ASCII animation instead of table rows")
    args = p.parse_args()

    num_proj = args.projections
    exposure_ms = args.exposure_ms
    display_ms = args.display_ms
    motor_speed = args.motor_speed

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    out_dir = Path(__file__).resolve().parent
    h5_path = out_dir / f"scan_{time.strftime('%Y%m%d_%H%M%S')}.h5"

    # Estimated frame period: motor step (angle_step / motor_speed) + exposure
    angle_step = 180.0 / max(num_proj - 1, 1)
    est_motor_ms = (angle_step / motor_speed) * 1000
    est_frame_ms = est_motor_ms + exposure_ms
    est_fps = 1000.0 / est_frame_ms if est_frame_ms > 0 else float("inf")
    display_hz = 1000.0 / display_ms
    drop_pct = (1.0 - est_frame_ms / display_ms) * 100 if display_ms > est_frame_ms else 0.0

    print()
    print(" Tomography scan — HDF5 logging + throttled live display")
    print(" " + "=" * 58)
    print(f" Projections: {num_proj}  |  Exposure: {exposure_ms:.0f} ms"
          f"  |  Display: {display_ms:.0f} ms")
    print(f" Motor speed: {motor_speed:.0f} deg/s"
          f"  |  Est. frame rate: {est_fps:.1f} fps"
          f"  |  Display rate: {display_hz:.1f} Hz")
    print(f" Estimated drop rate: {drop_pct:.0f}%"
          f"  |  One operator: sample()")
    print(" " + "=" * 58)
    print(f" HDF5: {h5_path}")
    print()

    # -- HDF5 file (pre-allocate) --
    f = h5py.File(h5_path, "w")
    ds = f.create_dataset(
        "projections",
        shape=(num_proj,),
        dtype=np.dtype([
            ("timestamp", "f8"),
            ("proj_index", "i4"),
            ("angle", "f4"),
            ("counts", "f8"),
            ("beam_current", "f4"),
            ("beam_posx", "f4"),
            ("beam_posy", "f4"),
        ]),
    )
    f.attrs["exposure_ms"] = exposure_ms
    f.attrs["motor_speed"] = motor_speed
    f.attrs["num_projections"] = num_proj

    # -- counters --
    hdf5_written = 0
    display_shown = 0
    scan_done = asyncio.Event()
    start_time = 0.0

    # -- build shared source --
    # tomography_scan() returns a cold Observable.  share() makes it hot:
    # one subscription to the source, many observers.
    source = tomography_scan(
        ctx,
        num_proj=num_proj,
        start_angle=0.0,
        stop_angle=180.0,
        exposure_ms=exposure_ms,
        motor_speed=motor_speed,
        scheduler=scheduler,
    ).pipe(ops.share())

    # -- branch 1: HDF5 writer (every frame) --
    def write_frame(frame):
        nonlocal hdf5_written
        ts, i, angle, counts, beam_cur, beam_px, beam_py = frame
        ds[i] = (ts, i, angle, counts, beam_cur, beam_px, beam_py)
        hdf5_written += 1

    async def on_scan_error(exc):
        try:
            pv, = await ctx.get_pvs("TOMO:SCAN:STATUS")
            await pv.write([3])
        except Exception:
            pass
        print(f"\nScan ERROR: {exc}", file=sys.stderr)
        scan_done.set()

    def _schedule_error(exc):
        asyncio.ensure_future(on_scan_error(exc))

    # -- branch 2: live display (throttled) --
    live_disp = None
    if args.ascii:
        live_disp = LiveDisplay(num_proj, display_ms)

        def display_frame_ascii(frame):
            nonlocal display_shown
            display_shown += 1
            live_disp(frame)

        display_handler = display_frame_ascii
    else:
        # -- header --
        print(f" {'Frame':>5}  {'Angle':>8}  {'Counts':>8}  {'Beam(mA)':>9}"
              f"  {'PosX(mm)':>10}  {'PosY(mm)':>10}  HDF5  Disp")
        print(" " + "-" * 78)

        def display_frame_table(frame):
            nonlocal display_shown
            ts, i, angle, counts, beam_cur, beam_px, beam_py = frame
            display_shown += 1
            pct = (i + 1) / num_proj * 100
            print(
                f"\r {i+1:5d}  {angle:8.3f}  {counts:8.0f}  {beam_cur:9.3f}"
                f"  {beam_px:10.5f}  {beam_py:10.5f}"
                f"  {hdf5_written:4d}  {display_shown:3d}"
                f"  {pct:3.0f}%",
                end="",
                flush=True,
            )

        display_handler = display_frame_table

    source.subscribe(
        on_next=write_frame,
        on_error=_schedule_error,
        scheduler=scheduler,
    )

    source.pipe(
        ops.sample(timedelta(milliseconds=display_ms), scheduler=scheduler),
    ).subscribe(
        on_next=display_handler,
        scheduler=scheduler,
    )

    # -- completion handler --
    def on_completed():
        scan_done.set()

    source.subscribe(
        on_next=lambda _: None,
        on_error=lambda e: (print(f"\nScan error: {e}", file=sys.stderr), scan_done.set()),
        on_completed=on_completed,
        scheduler=scheduler,
    )

    # -- capture start time from first frame --
    def capture_start(frame):
        nonlocal start_time
        if start_time == 0.0:
            start_time = frame[0]

    source.subscribe(
        on_next=capture_start,
        scheduler=scheduler,
    )

    await scan_done.wait()
    f.close()

    if live_disp is not None:
        live_disp.cleanup()

    elapsed = time.time() - start_time if start_time else 0
    actual_fps = num_proj / elapsed if elapsed > 0 else 0
    actual_drop = (1.0 - display_shown / hdf5_written) * 100 if hdf5_written else 0

    if not args.ascii:
        print()

    w = min(shutil.get_terminal_size().columns, 78)
    print(" " + "=" * w)
    print(f" Scan complete.")
    print(f" Frames acquired: {hdf5_written}  |  Frames displayed: {display_shown}"
          f"  |  Actual drop: {actual_drop:.0f}%")
    print(f" Elapsed: {elapsed:.2f}s  |  Actual fps: {actual_fps:.1f}")
    print(f" HDF5 saved to: {h5_path}")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()

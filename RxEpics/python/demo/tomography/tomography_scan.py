"""Tomography acquisition with HDF5 logging and throttled live display.

A tomography scan acquires projections at high rate. Two consumers share
the same data stream:

  1. HDF5 writer — stores every projection (must keep up)
  2. Live display — shows projections at human speed via sample()

The slow display consumer never backpressures the source — sample() drops
intermediate frames silently. One operator replaces queues, locks, flags,
and manual accounting.

Usage:
    python tomography_scan.py [--projections 360] [--exposure-ms 30] [--display-ms 250]
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import h5py
import numpy as np
import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from caproto.asyncio.client import Context

# -- helpers ------------------------------------------------------------------

async def _read(ctx: Context, name: str) -> float:
    pv, = await ctx.get_pvs(name)
    return (await pv.read()).data[0]


async def _write(ctx: Context, name: str, value) -> None:
    pv, = await ctx.get_pvs(name)
    await pv.write([value])


# -- scan source --------------------------------------------------------------

def tomography_scan(
    ctx: Context,
    num_proj: int = 360,
    start_angle: float = 0.0,
    stop_angle: float = 180.0,
    exposure_ms: float = 30.0,
    motor_speed: float = 10.0,
) -> rx.Observable:
    """Return a cold Observable that runs a tomography scan.

    Each emission is a tuple: (timestamp, proj_index, angle, counts,
    beam_current, beam_posx, beam_posy).
    """

    def subscribe(observer, scheduler=None):
        async def _run():
            try:
                await _write(ctx, "TOMO:ROT:SPEED", motor_speed)
                await _write(ctx, "TOMO:DET:EXPOSURE", exposure_ms)
                await _write(ctx, "TOMO:SCAN:STATUS", 1)  # RUNNING

                angles = [
                    start_angle + i * (stop_angle - start_angle) / max(num_proj - 1, 1)
                    for i in range(num_proj)
                ]

                for i, angle in enumerate(angles):
                    # --- move motor and wait for settle ---
                    await _write(ctx, "TOMO:ROT:VAL", angle)
                    while True:
                        movn = await _read(ctx, "TOMO:ROT:MOVN")
                        if movn == 0:
                            break
                        await asyncio.sleep(0.005)

                    # --- trigger detector ---
                    await _write(ctx, "TOMO:DET:ACQUIRE", 1)
                    # wait for simulator to set ACQUIRING=1
                    for _ in range(500):
                        if await _read(ctx, "TOMO:DET:ACQUIRING") == 1:
                            break
                        await asyncio.sleep(0.001)
                    # wait for exposure to finish (ACQUIRING → 0)
                    for _ in range(5000):
                        if await _read(ctx, "TOMO:DET:ACQUIRING") == 0:
                            break
                        await asyncio.sleep(0.001)

                    # --- read results ---
                    counts = await _read(ctx, "TOMO:DET:COUNTS")
                    beam_cur = await _read(ctx, "TOMO:BEAM:CURRENT")
                    beam_px = await _read(ctx, "TOMO:BEAM:POSX")
                    beam_py = await _read(ctx, "TOMO:BEAM:POSY")
                    ts = time.time()

                    # --- update scan PVs ---
                    await _write(ctx, "TOMO:SCAN:CUR_ANGLE", angle)
                    await _write(ctx, "TOMO:SCAN:CUR_PROJ", i)

                    observer.on_next((ts, i, angle, counts, beam_cur, beam_px, beam_py))

                await _write(ctx, "TOMO:SCAN:STATUS", 2)  # DONE
                observer.on_completed()

            except Exception as exc:
                try:
                    await _write(ctx, "TOMO:SCAN:STATUS", 3)  # ABORTED
                except Exception:
                    pass
                observer.on_error(exc)

        task = asyncio.ensure_future(_run())

        def dispose():
            task.cancel()

        return dispose

    return rx.create(subscribe)


# -- main ---------------------------------------------------------------------

async def main():
    p = argparse.ArgumentParser(description="Tomography scan — HDF5 + live display")
    p.add_argument("--projections", type=int, default=360)
    p.add_argument("--exposure-ms", type=float, default=30.0)
    p.add_argument("--display-ms", type=float, default=250.0)
    p.add_argument("--motor-speed", type=float, default=10.0,
                   help="Motor speed in deg/s (higher = faster scan)")
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

    # -- header --
    print(f" {'Frame':>5}  {'Angle':>8}  {'Counts':>8}  {'Beam(mA)':>9}"
          f"  {'PosX(mm)':>10}  {'PosY(mm)':>10}  HDF5  Disp")
    print(" " + "-" * 78)

    # -- build shared source --
    source = tomography_scan(
        ctx,
        num_proj=num_proj,
        start_angle=0.0,
        stop_angle=180.0,
        exposure_ms=exposure_ms,
        motor_speed=motor_speed,
    ).pipe(ops.share())

    # -- branch 1: HDF5 writer (every frame) --
    def write_frame(frame):
        nonlocal hdf5_written
        ts, i, angle, counts, beam_cur, beam_px, beam_py = frame
        ds[i] = (ts, i, angle, counts, beam_cur, beam_px, beam_py)
        hdf5_written += 1

    def on_hdf5_error(exc):
        print(f"\nHDF5 ERROR: {exc}", file=sys.stderr)
        scan_done.set()

    source.subscribe(
        on_next=write_frame,
        on_error=on_hdf5_error,
        on_completed=lambda: None,
        scheduler=scheduler,
    )

    # -- branch 2: live display (throttled) --
    def display_frame(frame):
        nonlocal display_shown
        ts, i, angle, counts, beam_cur, beam_px, beam_py = frame
        display_shown += 1
        elapsed = ts - start_time if start_time else 0
        pct = (i + 1) / num_proj * 100
        print(
            f"\r {i+1:5d}  {angle:8.3f}  {counts:8.0f}  {beam_cur:9.3f}"
            f"  {beam_px:10.5f}  {beam_py:10.5f}"
            f"  {hdf5_written:4d}  {display_shown:3d}"
            f"  {pct:3.0f}%",
            end="",
            flush=True,
        )

    def on_display_error(exc):
        print(f"\nDisplay error: {exc}", file=sys.stderr)

    source.pipe(
        ops.sample(timedelta(milliseconds=display_ms), scheduler=scheduler),
    ).subscribe(
        on_next=display_frame,
        on_error=on_display_error,
        scheduler=scheduler,
    )

    # -- completion handler --
    def on_scan_completed():
        scan_done.set()

    source.subscribe(
        on_next=lambda _: None,
        on_error=lambda e: (print(f"\nScan error: {e}", file=sys.stderr), scan_done.set()),
        on_completed=on_scan_completed,
        scheduler=scheduler,
    )

    # record start time when first frame arrives
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

    elapsed = time.time() - start_time if start_time else 0
    actual_fps = num_proj / elapsed if elapsed > 0 else 0
    actual_drop = (1.0 - display_shown / hdf5_written) * 100 if hdf5_written else 0

    print()
    print(" " + "=" * 58)
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

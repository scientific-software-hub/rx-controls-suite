"""Guarded Tomography Scan — Bluesky RunEngine × rx-controls-suite.

The same guarded scan as ../guarded_scan.py, with the orchestration handed
to Bluesky and the streams kept in rx.  Division of labour:

  Bluesky owns                          rx-controls-suite owns
  ─────────────────────────────         ─────────────────────────────────────
  the plan (bp.scan)                    every device verb (write → poll → done)
  suspend / resume / rewind             the 1 Hz cross-system health stream
  Event documents + metadata            the Tango side (Bluesky has no Tango)
  checkpoints and clean aborts          the document fan-out: HDF5 vs display

The four fault patterns, re-mapped:

  • Beam-loss recovery   — pure-rx `filter + take(1)` gate becomes a Bluesky
                           *suspender* driven by an RxSignal over the Tango
                           health stream.  pre/post plans close and re-open
                           the shutter; the RunEngine rewinds to the last
                           checkpoint, so the interrupted step is re-taken.

  • Orbit-drift flagging — the RingHealth Readable rides along in bp.scan's
                           detector list; every Event document carries Tango
                           orbit + quality next to the EPICS counts.

  • Vacuum-burst abort   — rx interlock stream → RE.request_pause() →
                           RE.abort(): documents get exit_status='abort',
                           teardown closes the shutter.

  • Backpressure         — RunEngine documents come *back* into rx: HDF5
                           subscribes raw (every event), the live display
                           through sample(display_ms).

Usage
-----
    ../../../.venv/bin/python guarded_scan_bluesky.py [--projections N]
        [--exposure-ms MS] [--display-ms MS] [--motor-speed DEG/S]

    # In a second terminal — same faults as the pure-rx demo:
    python ../inject_fault.py beam_loss      # suspender trips, shutter closes
    python ../inject_fault.py nominal        # suspender releases, step re-taken
    python ../inject_fault.py orbit_drift    # quality_ok=False in documents
    python ../inject_fault.py vacuum_burst   # RE.abort, exit_status='abort'
"""

import os

# The demo IOC is host-networked; point CA at localhost before caproto loads.
os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")
os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")

import argparse
import logging
import sys
import threading
import time
from datetime import timedelta
from functools import partial
from pathlib import Path

import h5py
import numpy as np
import reactivex.operators as ops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from facility import (  # noqa: E402
    MIN_BEAM_CURRENT, SCAN_RUNNING, SCAN_DONE, SCAN_ABORTED,
    PV_ROT_SPEED, PV_DET_EXPOSURE, PV_SHUTTER,
    PV_SCAN_STATUS, PV_SCAN_CUR_ANGLE, PV_SCAN_CUR_PROJ,
    ring_health,
)
from rx_bluesky import RxLoop, RxSignal, documents  # noqa: E402
from devices import PVDevice, RotationMotor, TomoDetector, RingHealth  # noqa: E402

import bluesky.plan_stubs as bps  # noqa: E402
import bluesky.plans as bp  # noqa: E402
from bluesky import RunEngine  # noqa: E402
from bluesky.suspenders import SuspendBoolLow  # noqa: E402
from bluesky.utils import RunEngineInterrupted  # noqa: E402
from caproto.asyncio.client import Context  # noqa: E402
from rxepics.channel_write import write_pv  # noqa: E402
import reactivex as rx  # noqa: E402


async def _make_context() -> Context:
    return Context()


def main() -> None:
    p = argparse.ArgumentParser(description="Guarded scan — Bluesky × rx-controls-suite")
    p.add_argument("--projections", type=int, default=36)
    p.add_argument("--exposure-ms", type=float, default=30.0)
    p.add_argument("--display-ms", type=float, default=250.0)
    p.add_argument("--motor-speed", type=float, default=10.0)
    args = p.parse_args()

    num_proj = args.projections

    # ── rx side: loop, context, shared health stream ──────────────────────────
    rx_loop = RxLoop()
    ctx = rx_loop.run(_make_context())
    health = ring_health(rx_loop.scheduler, interval_ms=1000)

    # ── devices: every verb is an rx pipeline ─────────────────────────────────
    motor    = RotationMotor("tomo_rot", ctx, rx_loop)
    detector = TomoDetector("tomo_det", ctx, rx_loop)
    ring     = RingHealth("storage_ring", ctx, rx_loop)
    shutter  = PVDevice("shutter",      PV_SHUTTER,      ctx, rx_loop)
    speed    = PVDevice("rot_speed",    PV_ROT_SPEED,    ctx, rx_loop)
    exposure = PVDevice("det_exposure", PV_DET_EXPOSURE, ctx, rx_loop)

    # ── RunEngine ──────────────────────────────────────────────────────────────
    RE = RunEngine({})
    # The RunEngine logs the full plan traceback on abort; the demo's abort is
    # deliberate, so keep the console to the printed status messages only.
    logging.getLogger("bluesky").addHandler(logging.NullHandler())
    logging.getLogger("bluesky").propagate = False

    # ── Pattern 1: beam-loss recovery as a suspender ──────────────────────────
    # The pure-rx demo gated each projection on filter(is_healthy) + take(1).
    # Here the same Tango health stream drives a Bluesky suspender: trip when
    # beam_ok goes False, close the shutter (pre_plan), re-open it on resume
    # (post_plan), rewind to the last checkpoint and re-take the step.
    beam_ok = health.pipe(ops.map(lambda h: h.current >= MIN_BEAM_CURRENT))
    RE.install_suspender(SuspendBoolLow(
        RxSignal(beam_ok, rx_loop, name="beam_ok"),
        sleep=1.0,
        pre_plan=partial(bps.mv, shutter, 0),
        post_plan=partial(bps.mv, shutter, 1),
        tripped_message=f"storage-ring beam below {MIN_BEAM_CURRENT:.0f} mA",
    ))

    # ── Pattern 3: vacuum-burst abort ─────────────────────────────────────────
    # The interlock stream fires once; a helper thread (never the rx loop —
    # request_pause blocks its caller) pauses the RunEngine, and the except
    # branch below converts the pause into a clean abort.
    interlock_tripped = threading.Event()

    def _on_interlock(h) -> None:
        interlock_tripped.set()
        print(f"\n  ⚠  VACUUM BURST: interlocks={h.interlocks} — pausing RunEngine for abort")

        def _pause():
            try:
                RE.request_pause()
            except Exception:
                pass  # scan may have already finished

        threading.Thread(target=_pause, daemon=True).start()

    rx_loop.subscribe(
        health.pipe(ops.filter(lambda h: h.interlocks > 0), ops.take(1)),
        on_next=_on_interlock,
    )

    # ── Patterns 2 + 4: documents back into rx ────────────────────────────────
    docs = documents(RE)

    h5_path = Path(__file__).resolve().parent / f"scan_bluesky_{time.strftime('%Y%m%d_%H%M%S')}.h5"
    h5 = h5py.File(h5_path, "w")
    ds = h5.create_dataset("projections", shape=(num_proj,), dtype=np.dtype([
        ("timestamp", "f8"), ("proj_index", "i4"), ("angle", "f4"),
        ("counts", "f8"), ("beam_posx", "f4"), ("beam_posy", "f4"),
        ("ring_current", "f4"), ("orbit_x", "f4"), ("quality_ok", "?"),
    ]))

    counters = {"written": 0, "displayed": 0, "flagged": 0}

    def write_frame(named_doc) -> None:
        name, doc = named_doc
        if name != "event":
            return
        d, i = doc["data"], doc["seq_num"] - 1
        ds[i] = (doc["time"], i, d["angle"], d["counts"], d["beam_posx"],
                 d["beam_posy"], d["ring_current"], d["orbit_x"], d["quality_ok"])
        counters["written"] += 1
        if not d["quality_ok"]:
            counters["flagged"] += 1

    docs.subscribe(on_next=write_frame)  # raw: every event reaches HDF5

    def show_frame(named_doc) -> None:
        _, doc = named_doc
        d = doc["data"]
        counters["displayed"] += 1
        q = "✓" if d["quality_ok"] else "~"
        print(f"  {doc['seq_num']:5d}  {d['angle']:7.2f}  {d['counts']:8.0f}  "
              f"{d['ring_current']:9.2f}  {d['orbit_x']:+11.1f}  "
              f"{d['beam_posx']:8.4f}  {d['beam_posy']:8.4f}  {q}")

    docs.pipe(
        ops.filter(lambda nd: nd[0] == "event"),
        ops.sample(timedelta(milliseconds=args.display_ms), scheduler=rx_loop.scheduler),
    ).subscribe(on_next=show_frame)

    # Mirror scan progress into the EPICS scan-state PVs so the existing web
    # dashboard (../live_dashboard.py) tracks the Bluesky scan unchanged.
    # observe_on hops from the RunEngine callback thread onto the rx loop,
    # where the rxepics write pipelines are allowed to subscribe.
    def _pv_updates(named_doc) -> rx.Observable:
        name, doc = named_doc
        if name == "start":
            return write_pv(PV_SCAN_STATUS, SCAN_RUNNING, ctx)
        if name == "event":
            return rx.zip(
                write_pv(PV_SCAN_CUR_ANGLE, doc["data"]["angle"], ctx),
                write_pv(PV_SCAN_CUR_PROJ, doc["seq_num"] - 1, ctx),
            )
        if name == "stop":
            status = SCAN_DONE if doc["exit_status"] == "success" else SCAN_ABORTED
            return write_pv(PV_SCAN_STATUS, status, ctx)
        return rx.empty()

    docs.pipe(
        ops.observe_on(rx_loop.scheduler),
        ops.flat_map(_pv_updates),
    ).subscribe(on_error=lambda e: print(f"  scan-PV mirror error: {e}", file=sys.stderr))

    # ── The plan ───────────────────────────────────────────────────────────────
    def guarded_tomo_plan():
        yield from bps.mv(speed, args.motor_speed, exposure, args.exposure_ms)
        yield from bps.mv(shutter, 1)
        yield from bp.scan(
            [detector, ring], motor, 0.0, 180.0, num_proj,
            md={"purpose": "rx-controls-suite × Bluesky guarded-scan demo"},
        )
        yield from bps.mv(shutter, 0)

    print()
    print("  Guarded Tomography Scan — Bluesky RunEngine × rx-controls-suite")
    print("  " + "=" * 64)
    print(f"  Projections: {num_proj}  |  Exposure: {args.exposure_ms:.0f} ms"
          f"  |  Display: {args.display_ms:.0f} ms")
    print("  Suspender:  beam < 50 mA → shutter closed, step re-taken on resume")
    print("  Abort:      interlock → RE.abort(), exit_status='abort'")
    print(f"  HDF5: {h5_path}")
    print()
    print(f"  {'Frame':>5}  {'Angle':>7}  {'Counts':>8}  "
          f"{'Ring(mA)':>9}  {'OrbitX(µm)':>11}  {'PosX':>8}  {'PosY':>8}  Q")
    print("  " + "-" * 78)

    # ── Run ────────────────────────────────────────────────────────────────────
    aborted = False
    start_time = time.time()
    try:
        RE(guarded_tomo_plan())
    except RunEngineInterrupted:
        if interlock_tripped.is_set():
            aborted = True
            RE.abort(reason="vacuum burst interlock")
        else:
            RE.stop()
    finally:
        h5.close()

    # ── Emergency teardown (rx side, mirrors the pure-rx demo) ────────────────
    if aborted:
        print()
        print("  ── Emergency teardown ────────────────────────────────────────")
        done = threading.Event()
        rx_loop.subscribe(
            rx.zip(
                write_pv(PV_SCAN_STATUS, SCAN_ABORTED, ctx),
                write_pv(PV_SHUTTER, 0, ctx),
            ),
            on_next=lambda _: print("  ✓ scan status = ABORTED | shutter CLOSED"),
            on_completed=done.set,
        )
        done.wait(5)

    elapsed = time.time() - start_time
    print()
    print("  " + "=" * 64)
    print("  Scan ABORTED (vacuum burst interlock)." if aborted else "  Scan complete.")
    print(f"  Events → HDF5: {counters['written']}"
          f"  |  displayed: {counters['displayed']}"
          f"  |  quality-flagged: {counters['flagged']}")
    print(f"  Elapsed: {elapsed:.2f}s  |  HDF5: {h5_path}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  stopped.")

"""Guarded Tomography Scan — Prefect flow.

Same guarded scan as ``../synchrotron-beamline/guarded_scan.py``, driven by
Prefect instead of a single ``asyncio.run(main())``. The rx pipeline inside
each sweep is unchanged — health gate, five-way EPICS×Tango zip, quality
flag, HDF5 write; what Prefect adds is visible orchestration:

    prepare_beamline  ──▶  run_sweep ×N  ──▶  finalize
       (retries=2)          (retries=0)       (always runs)

Beam loss — two tiers
----------------------
Tier 1 is already inside ``guarded_acquire_projection``: each projection
waits for a healthy beam before starting. Ordinary dropouts are invisible
here — just log lines.

Tier 2 is ``sustained_low``: if beam stays down for ``--watchdog-s`` seconds
continuously, the current sweep task returns early and this flow calls
``pause_flow_run()`` — the flow run shows **Paused** in the Prefect UI with
a reason. An rx subscription armed *before* the pause (``pause_until_healthy``)
calls ``resume_flow_run`` the moment beam recovers, and the interrupted sweep
picks up exactly where it left off.

Interlock (vacuum burst) aborts the run: ``run_sweep`` raises
``InterlockAbort``, the flow catches it, writes SCAN_ABORTED + closes the
shutter, and the flow run ends **Failed** with the interlock as the reason.

Usage
-----
    python prefect_flow.py [--projections N] [--sweeps N] [--exposure-ms MS]
                           [--motor-speed DEG/S] [--watchdog-s S]

Prerequisites
-------------
    cd ../synchrotron-beamline && docker compose up -d --build
    export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
    docker compose up -d                      # this dir — Prefect server :4200
    export PREFECT_API_URL=http://127.0.0.1:4200/api

Then, in a second terminal, try these against a running scan:
    python ../synchrotron-beamline/inject_fault.py beam_loss
    python ../synchrotron-beamline/inject_fault.py nominal
    python ../synchrotron-beamline/inject_fault.py orbit_drift
    python ../synchrotron-beamline/inject_fault.py vacuum_burst
"""

import argparse
import sys
from pathlib import Path

from prefect import flow, get_run_logger, pause_flow_run, task
from prefect.artifacts import create_link_artifact, create_markdown_artifact
from prefect.runtime import flow_run as flow_run_ctx

from scan_core import (
    ScanEvent, ScanRun, make_context, ring_health, scan_setup, scan_teardown,
    shutter_supervisor, sustained_low, sweep_angles, sweep_frames, to_events,
    SCAN_ABORTED, SCAN_DONE,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "synchrotron-beamline" / "bluesky"))
from rx_bluesky import RxLoop, rx_wait  # noqa: E402

from rx_prefect import (  # noqa: E402
    ProgressTracker, drain, log_event, progress_ticks, pause_until_healthy,
    sweep_table,
)

import reactivex as rx
import reactivex.operators as ops


class InterlockAbort(Exception):
    """Raised when a vacuum-burst interlock aborts the scan mid-sweep."""


# ── tasks ────────────────────────────────────────────────────────────────────

@task(name="prepare-beamline", retries=2, retry_delay_seconds=3, persist_result=False)
def prepare_beamline(ctx, rx_loop, exposure_ms: float, motor_speed: float) -> None:
    logger = get_run_logger()
    rx_wait(scan_setup(ctx, exposure_ms, motor_speed), rx_loop, timeout=10.0)
    logger.info(f"beamline armed — exposure={exposure_ms:.0f}ms speed={motor_speed:.0f}deg/s")


@task(name="run-sweep", retries=0, persist_result=False)
def run_sweep(
    ctx, rx_loop, health, run: ScanRun, tracker: ProgressTracker,
    angles: list[float], index_offset: int, watchdog_s: float,
):
    """Acquire one sweep's projections (or the remainder of one, after a
    watchdog pause). Returns ``(next_index, watchdog_hit, frame_events)`` —
    ``watchdog_hit`` is True iff beam stayed down long enough to cut this
    call short (see ``sustained_low``); the flow decides what to do next and
    accumulates ``frame_events`` across calls so one sweep's table artifact
    always covers the whole sweep, even if a pause split it into two calls."""
    logger = get_run_logger()

    stop = sustained_low(health, watchdog_s, rx_loop.scheduler)
    frames = sweep_frames(
        ctx, health, angles, index_offset, rx_loop.scheduler, stop_trigger=stop,
    ).pipe(ops.share())  # shared: to_events and progress_ticks both read it once

    combined = rx.merge(
        to_events(frames, health),
        progress_ticks(frames, rx_loop),
    )

    collected: list[ScanEvent] = []

    def _on_event(ev: ScanEvent) -> None:
        if ev.kind == "progress_tick":
            tracker.push(index_offset + len(collected))
            return
        log_event(ev, logger)
        if ev.kind == "frame":
            collected.append(ev)
            p = ev.payload
            run.write_frame((
                ev.ts, p["index"], p["angle"], p["counts"],
                p["beam_posx"], p["beam_posy"], p["ring_current"],
                p["orbit_x"], p["quality_ok"],
            ))
        elif ev.kind == "interlock":
            raise InterlockAbort(f"interlocks={ev.payload.get('interlocks')}")

    drain(combined, rx_loop, _on_event)

    frame_count = len(collected)
    watchdog_hit = frame_count < len(angles)
    return index_offset + frame_count, watchdog_hit, collected


@task(name="finalize", persist_result=False)
def finalize(run: ScanRun, outcome: str, abort_reason: str | None, pauses: int, total: int) -> None:
    logger = get_run_logger()
    quality_pct = (
        100.0 * run.quality_ok_count / run.frames_written if run.frames_written else 0.0
    )
    lines = [
        f"# Tomography scan — {outcome}",
        "",
        "| metric | value |",
        "|---|---|",
        f"| frames acquired | {run.frames_written} / {total} |",
        f"| quality OK | {quality_pct:.0f}% |",
        f"| beam-loss pauses | {pauses} |",
        f"| outcome | {outcome} |",
    ]
    if abort_reason:
        lines.append(f"| abort reason | {abort_reason} |")
    create_markdown_artifact("\n".join(lines), key="tomo-summary", description="Scan summary")
    create_link_artifact(link=f"file://{run.path}", link_text=run.path.name, key="tomo-file")
    logger.info(
        f"scan {outcome}: {run.frames_written}/{total} frames, "
        f"{quality_pct:.0f}% quality, {pauses} pause(s)"
    )


# ── flow ─────────────────────────────────────────────────────────────────────

@flow(name="tomography-scan", log_prints=True)
def tomography_scan(
    projections: int = 36,
    sweeps: int = 3,
    exposure_ms: float = 30.0,
    motor_speed: float = 10.0,
    watchdog_s: float = 8.0,
) -> str:
    logger = get_run_logger()
    rx_loop = RxLoop()
    ctx = rx_loop.run(make_context())
    health = ring_health(rx_loop.scheduler, interval_ms=1000)

    out_dir = Path(__file__).resolve().parent
    run = ScanRun(out_dir, projections, exposure_ms, motor_speed, orchestrator="prefect")
    tracker = ProgressTracker(total=projections)
    # Also the flow's one long-lived subscriber to `health` (shared via
    # ops.share() in ring_health()): keeps the 1 Hz ring poll connected for
    # the whole flow, so it doesn't drop and reconnect between sweep tasks.
    dispose_shutter = rx_loop.subscribe(shutter_supervisor(ctx, health), on_next=lambda _ok: None)

    outcome, abort_reason, pauses = "completed", None, 0
    index_offset = 0
    caught: InterlockAbort | None = None

    try:
        prepare_beamline(ctx, rx_loop, exposure_ms, motor_speed)

        for sweep_idx, angles in enumerate(sweep_angles(projections, sweeps)):
            sweep_start = index_offset
            remaining = angles
            sweep_events: list[ScanEvent] = []
            while True:
                index_offset, watchdog_hit, chunk = run_sweep(
                    ctx, rx_loop, health, run, tracker,
                    remaining, index_offset, watchdog_s,
                )
                sweep_events.extend(chunk)
                if not watchdog_hit:
                    break

                pauses += 1
                dispose_resume = pause_until_healthy(health, rx_loop, flow_run_ctx.id)
                logger.warning(
                    f"beam down {watchdog_s:.0f}s+ — pausing flow run for operator visibility"
                )
                try:
                    pause_flow_run(timeout=600)
                finally:
                    dispose_resume()
                logger.info("beam recovered — resuming sweep")
                remaining = angles[index_offset - sweep_start:]

            if sweep_events:
                sweep_table(sweep_events, key=f"tomo-sweep-{sweep_idx}")
    except InterlockAbort as exc:
        outcome = "aborted"
        abort_reason = str(exc)
        caught = exc
    finally:
        dispose_shutter()

    status = SCAN_ABORTED if outcome == "aborted" else SCAN_DONE
    rx_wait(scan_teardown(ctx, status), rx_loop, timeout=10.0)
    run.close()

    finalize(run, outcome, abort_reason, pauses, projections)

    if caught is not None:
        # Teardown + the summary/link artifacts are already written above —
        # re-raise so the flow run itself ends Failed (red, with this as the
        # reason) rather than a Completed run whose outcome is buried in a
        # return value. A real facility would want interlock aborts wired
        # into Prefect's own failure notifications/automations.
        raise caught
    return outcome


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Guarded tomography scan — Prefect flow")
    p.add_argument("--projections", type=int, default=36)
    p.add_argument("--sweeps", type=int, default=3)
    p.add_argument("--exposure-ms", type=float, default=30.0)
    p.add_argument("--motor-speed", type=float, default=10.0)
    p.add_argument(
        "--watchdog-s", type=float, default=8.0,
        help="Sustained beam-loss duration before pausing the flow run",
    )
    args = p.parse_args()
    result = tomography_scan(
        projections=args.projections, sweeps=args.sweeps,
        exposure_ms=args.exposure_ms, motor_speed=args.motor_speed,
        watchdog_s=args.watchdog_s,
    )
    print(f"\n  Flow finished: {result}\n")

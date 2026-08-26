"""Rx ↔ Prefect bridge.

Parallel to ``../synchrotron-beamline/bluesky/rx_bluesky.py``'s four
adapters, this module is Prefect's four:

    drain               ScanEvent stream    →  blocking, on the CALLING thread
    log_event            one ScanEvent       →  a Prefect log line
    ProgressTracker      sampled frame count →  a live progress artifact
    sweep_table           one sweep's frames  →  a table artifact
    pause_until_healthy  health recovery     →  resume_flow_run

Threading model — the one thing worth reading carefully
---------------------------------------------------------
``rx_bluesky.RxLoop`` runs every rx subscription on its own dedicated
asyncio-loop thread (rxepics/rxtango schedule work with
``asyncio.ensure_future`` and need a running loop where they subscribe).
Prefect's run context — the thing ``get_run_logger()`` and every artifact
function key off — is thread-local: it does **not** cross into the rx loop
thread. Calling a Prefect SDK function from an ``on_next`` callback that
fires on the rx loop would either silently no-op or raise, and worse, do so
inconsistently depending on which Prefect call it is:

  - ``get_run_logger()`` / artifact creators key off
    ``prefect.context.get_run_context()`` — on the rx loop thread that
    raises ``MissingContextError``, so there is no run to attach the
    log/artifact to.
  - Several Prefect functions (``pause_flow_run``, ``resume_flow_run``, the
    artifact creators) are additionally wrapped in ``@async_dispatch``, which
    decides sync-vs-async by checking ``get_run_context()`` first and, on
    ``MissingContextError``, falls back to ``asyncio.get_running_loop()``.
    The rx loop thread always has one running — that's how
    ``AsyncIOThreadSafeScheduler`` dispatches callbacks — so the check
    (wrongly, for our purposes) concludes "async context" and returns an
    **unawaited coroutine**. Nothing raises; the call is simply a no-op.

So: no Prefect SDK call may run on the rx loop thread. ``drain()`` is the
fix — it only ever *enqueues* on the rx loop thread; the calling (task)
thread dequeues and invokes every callback, so every side effect the caller
performs (logging, artifacts, HDF5 writes) happens on its own thread, with
its own valid run context.

The one call that cannot use ``drain()`` is ``resume_flow_run`` — it fires
while the *flow's own thread* is blocked inside ``pause_flow_run()``, so
there is no task thread free to drain onto. It still can't run on the rx
loop thread for the ``async_dispatch`` reason above, so ``pause_until_healthy``
hops onto a private ``ThreadPoolScheduler(1)`` first — a plain worker thread
with no run context and no running loop, so ``async_dispatch`` correctly
picks the sync path. Same idiom ``rx_bluesky.RxSignal`` uses to keep the rx
loop free for device reads; here it's keeping Prefect calls off a thread
they can't work from at all.
"""

import queue
from datetime import timedelta

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler import ThreadPoolScheduler

from prefect.artifacts import (
    create_progress_artifact, create_table_artifact, update_progress_artifact,
)
from prefect.flow_runs import resume_flow_run

from scan_core import ScanEvent, is_healthy


# ── the rx-loop → task-thread boundary ──────────────────────────────────────

def drain(events: rx.Observable, rx_loop, on_event, timeout: float | None = None) -> None:
    """Run *events* to completion, calling ``on_event(ev)`` on the CALLING
    thread — never on the rx loop thread. See module docstring.

    The rx loop thread only ever ``queue.put``s; this function's own thread
    (the Prefect task that calls it) pulls from the queue and invokes
    *on_event*, so every Prefect SDK call *on_event* makes is safe. If
    *on_event* raises, the exception propagates out of this call normally —
    on the calling thread, where Prefect expects a task to fail.
    """
    q: "queue.Queue[tuple[str, object]]" = queue.Queue()

    dispose = rx_loop.subscribe(
        events,
        on_next=lambda ev: q.put(("next", ev)),
        on_error=lambda exc: q.put(("error", exc)),
        on_completed=lambda: q.put(("completed", None)),
    )
    try:
        while True:
            kind, payload = q.get(timeout=timeout)
            if kind == "next":
                on_event(payload)
            elif kind == "error":
                raise payload
            else:
                return
    finally:
        dispose()


# ── ScanEvent → log line ────────────────────────────────────────────────────

def log_event(ev: ScanEvent, logger) -> None:
    """One ``ScanEvent`` → one Prefect log line. Call only from the task/flow
    thread — *logger* (from ``get_run_logger()``) is bound to that thread's
    run context."""
    if ev.kind == "frame":
        p = ev.payload
        q = "OK" if p["quality_ok"] else "LOW"
        logger.info(
            f"[{ev.seq:04d}] frame {p['index']:3d}  angle={p['angle']:6.2f}deg  "
            f"counts={p['counts']:.0f}  ring={p['ring_current']:.2f}mA  "
            f"orbit={p['orbit_x']:+.1f}um  quality={q}"
        )
    elif ev.kind == "beam_low":
        logger.warning("beam LOW — shutter closing, next projection will wait")
    elif ev.kind == "beam_ok":
        logger.info("beam OK — shutter open")
    elif ev.kind == "interlock":
        logger.error(f"INTERLOCK — interlocks={ev.payload.get('interlocks')}")
    # "progress_tick" (see prefect_flow.py) is handled by the caller, not logged


# ── live progress artifact ──────────────────────────────────────────────────

class ProgressTracker:
    """One progress artifact, created once and updated in place across sweep
    task boundaries — the Prefect Artifacts counterpart to ``ScanRun``: both
    are plain objects a ``persist_result=False`` task carries between calls
    in the same process.

    ``push()`` is a plain synchronous method (no rx subscription of its own)
    — call it from ``on_event`` on the task thread, same as ``log_event``.
    """

    def __init__(self, total: int, key: str = "tomo-progress"):
        self.total = total
        self.artifact_id = create_progress_artifact(
            progress=0.0, key=key, description="Projections acquired",
        )

    def push(self, done: int) -> None:
        update_progress_artifact(
            self.artifact_id, progress=100.0 * done / max(self.total, 1),
        )


def progress_ticks(frames: rx.Observable, rx_loop, sample_ms: int = 500) -> rx.Observable:
    """Sample a **shared** frame stream at *sample_ms* and turn each sample
    into a ``progress_tick`` ScanEvent.

    Same ``share()`` + ``sample()`` idiom that throttles the ASCII display in
    ``guarded_scan.py`` (``source.pipe(ops.sample(display_ms))``) — here it
    throttles calls to the Prefect API instead of a terminal. *frames* must
    already be ``.pipe(ops.share())``-d by the caller (see ``to_events``'s
    docstring) so this doesn't trigger a second, duplicate acquisition.
    """
    return frames.pipe(
        ops.sample(timedelta(milliseconds=sample_ms), scheduler=rx_loop.scheduler),
        ops.map(lambda f: ScanEvent(kind="progress_tick", ts=f[0], seq=-1, payload={})),
    )


# ── per-sweep table artifact ────────────────────────────────────────────────

def sweep_table(frame_events: list[ScanEvent], key: str) -> None:
    """One sweep's frames as a Prefect table artifact."""
    rows = [
        {
            "index": ev.payload["index"],
            "angle_deg": round(ev.payload["angle"], 2),
            "counts": ev.payload["counts"],
            "ring_mA": round(ev.payload["ring_current"], 2),
            "orbit_um": round(ev.payload["orbit_x"], 1),
            "quality": "OK" if ev.payload["quality_ok"] else "LOW",
        }
        for ev in frame_events
        if ev.kind == "frame"
    ]
    create_table_artifact(table=rows, key=key, description=f"Frames — {key}")


# ── beam recovery → resume_flow_run ─────────────────────────────────────────

def pause_until_healthy(health: rx.Observable, rx_loop, flow_run_id):
    """Arm auto-resume *before* the flow calls ``pause_flow_run``.

    Must run off the rx loop thread — see module docstring. Returns a
    zero-arg dispose function; call it once the flow has resumed (whether
    via this callback or, e.g., a manual resume from the UI) to avoid a
    stray subscription outliving the pause.
    """
    pool = ThreadPoolScheduler(1)
    return rx_loop.subscribe(
        health.pipe(
            ops.filter(is_healthy),
            ops.take(1),
            ops.observe_on(pool),
        ),
        on_next=lambda _h: resume_flow_run(flow_run_id),
    )

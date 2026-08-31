"""Orchestrator-agnostic scan core — the seam workflow engines plug into.

This module contains **no** Prefect, n8n, or any other orchestrator import.
It reuses the pure-rx guarded scan from ``../synchrotron-beamline`` almost
unchanged — the per-projection pipeline (health gate, five-way EPICS×Tango
``rx.zip``, quality flag, ``TOMO:SCAN:*`` progress writes) already lives in
``guarded_acquire_projection()`` and is imported directly rather than
reimplemented. What this module adds on top is only what an *external*
orchestrator needs and the original single-process script didn't:

  - ``sweep_angles`` / ``sweep_frames``  — cut one scan into N contiguous
    sweeps, so an orchestrator can drive it as N visible steps instead of
    one opaque call.
  - ``ScanEvent`` / ``to_events``        — a flat, orchestrator-neutral event
    stream (frame / beam_ok / beam_low / interlock) that any bridge module
    (``rx_prefect.py``, ``rx_n8n.py`` / ``scan_service.py``) turns into its
    own vocabulary (logs, artifacts, SSE frames, node outputs, ...).
  - ``drain``                            — the rx-loop → calling-thread
    boundary; both bridges need it, so it lives here rather than in one.
  - ``sustained_low``                    — a *second* beam-loss tier on top
    of the existing per-projection gate: fires once beam has been low
    continuously for N seconds, for an orchestrator to escalate to (e.g.
    Prefect's ``pause_flow_run``). Ordinary dropouts stay invisible to the
    orchestrator, exactly as they are in the original demo.
  - ``ScanRun``                          — the HDF5 file, factored out of
    ``guarded_scan.py``'s ``main()`` so any orchestrator-side task can own
    and close it without owning the acquisition pipeline too.
  - ``make_context``                     — the one-line caproto Context
    factory, because a caproto ``Context`` binds to whatever event loop is
    running when it's constructed and every orchestrator bridge needs to
    get that right on its own loop.

Path bootstrap mirrors ``demo/reactive-query-cache/querycache_dashboard.py``:
reuse the sibling demo's constants and pipeline rather than duplicating them.
"""

import queue
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context

# ── path bootstrap ──────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))
# reuse the sibling demo's facility.py + guarded_scan.py — no duplication
sys.path.insert(0, str(_ROOT / "demo" / "synchrotron-beamline"))

from facility import (  # noqa: E402
    MIN_BEAM_CURRENT, ORBIT_ALARM,
    SCAN_RUNNING, SCAN_DONE, SCAN_ABORTED,
    PV_ROT_SPEED, PV_DET_EXPOSURE, PV_SHUTTER, PV_SCAN_STATUS,
    Health, is_healthy, ring_health,
)
from guarded_scan import guarded_acquire_projection  # noqa: E402

from rxepics.channel_write import write_pv  # noqa: E402


# ── caproto Context factory ─────────────────────────────────────────────────

async def make_context() -> Context:
    """Create a caproto Context bound to the calling coroutine's event loop.

    caproto binds internal queues to ``get_running_loop()`` at construction,
    so this must be awaited on whatever loop will run every subsequent PV
    read/write for the scan — e.g. ``rx_loop.run(make_context())``.
    """
    return Context()


# ── scan setup / teardown ───────────────────────────────────────────────────

def scan_setup(ctx: Context, exposure_ms: float, motor_speed: float) -> rx.Observable:
    """Arm the beamline: motor speed, exposure, STATUS=RUNNING, shutter open.

    Emits ``True`` once, then completes — block on it with ``rx_wait``.
    """
    return write_pv(PV_ROT_SPEED, motor_speed, ctx).pipe(
        ops.flat_map(lambda _: write_pv(PV_DET_EXPOSURE, exposure_ms, ctx)),
        ops.flat_map(lambda _: write_pv(PV_SCAN_STATUS, SCAN_RUNNING, ctx)),
        ops.flat_map(lambda _: write_pv(PV_SHUTTER, 1, ctx)),
        ops.map(lambda _: True),
    )


def scan_teardown(ctx: Context, status: int) -> rx.Observable:
    """Write the final SCAN:STATUS; also close the shutter when aborting.

    Emits ``True`` once, then completes.
    """
    obs = write_pv(PV_SCAN_STATUS, status, ctx)
    if status == SCAN_ABORTED:
        obs = obs.pipe(ops.flat_map(lambda _: write_pv(PV_SHUTTER, 0, ctx)))
    return obs.pipe(ops.map(lambda _: True))


def shutter_supervisor(ctx: Context, health: rx.Observable) -> rx.Observable:
    """Auto-close/open the shutter on beam-health transitions.

    Same idiom as ``guarded_scan.py``'s supervisor: map → distinct_until_changed
    → flat_map(write_pv). Emits the new shutter state (bool) on every
    transition; never completes on its own — the caller subscribes once for
    the life of the scan and disposes at the end.
    """
    return health.pipe(
        ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),
        ops.distinct_until_changed(),
        ops.flat_map(lambda ok: write_pv(PV_SHUTTER, 1 if ok else 0, ctx).pipe(
            ops.map(lambda _: ok))),
    )


# ── sweeps ───────────────────────────────────────────────────────────────────

def sweep_angles(
    num_proj: int, num_sweeps: int, start: float = 0.0, stop: float = 180.0,
) -> list[list[float]]:
    """Partition the scan's angle range into *num_sweeps* contiguous chunks.

    Same angle generation as ``guarded_scan.py``'s ``guarded_scan()`` — the
    full-range list is identical no matter how many sweeps it's cut into;
    only the grouping changes. Sizes differ by at most one projection when
    *num_proj* doesn't divide evenly.
    """
    step = (stop - start) / max(num_proj - 1, 1)
    angles = [start + i * step for i in range(num_proj)]

    base, rem = divmod(num_proj, num_sweeps)
    sizes = [base + (1 if i < rem else 0) for i in range(num_sweeps)]

    sweeps: list[list[float]] = []
    idx = 0
    for size in sizes:
        sweeps.append(angles[idx: idx + size])
        idx += size
    return sweeps


def sweep_frames(
    ctx: Context,
    health: rx.Observable,
    angles: list[float],
    index_offset: int,
    scheduler,
    stop_trigger: rx.Observable | None = None,
    indices: list[int] | None = None,
) -> rx.Observable:
    """One sweep's frames: a concat of ``guarded_acquire_projection`` calls.

    By default frame indices run ``index_offset .. index_offset + len(angles)
    - 1`` so HDF5 rows land at the right absolute slot regardless of which
    sweep produced them. Pass *indices* (same length as *angles*, e.g. from
    ``refine.refine_points``) to re-acquire an arbitrary, non-contiguous set
    of projections at their *original* row indices — a refinement pass
    overwrites existing rows rather than appending; *index_offset* is then
    unused.

    If *stop_trigger* fires mid-sweep, the concat is cut short
    (``take_until``) — the caller sees fewer frames than ``len(angles)`` and
    decides what that means (escalate, abort, ...).
    """
    if indices is None:
        indices = [index_offset + i for i in range(len(angles))]
    projections = [
        guarded_acquire_projection(angle, idx, ctx, health, scheduler)
        for idx, angle in zip(indices, angles)
    ]
    frames = rx.concat(*projections)
    if stop_trigger is not None:
        frames = frames.pipe(ops.take_until(stop_trigger))
    return frames


# ── beam-loss watchdog (tier 2) ─────────────────────────────────────────────

def sustained_low(health: rx.Observable, seconds: float, scheduler) -> rx.Observable:
    """Fire once beam has been continuously low for *seconds*, then complete.

    Tier 1 (the per-projection ``wait_healthy`` gate inside
    ``guarded_acquire_projection``) already absorbs ordinary dropouts —
    nothing about this function changes that. This is tier 2: a longer,
    *sustained* dropout an orchestrator may want to react to visibly (e.g.
    pause a flow run) rather than let ride silently.

    A brief flicker never fires this: ``switch_map`` cancels the pending
    timer the instant beam recovers, restarting only on the next drop.
    """
    return health.pipe(
        ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),
        ops.distinct_until_changed(),
        ops.switch_map(lambda ok: rx.empty() if ok
                       else rx.timer(timedelta(seconds=seconds), scheduler=scheduler)),
        ops.take(1),
    )


def interlock_trigger(health: rx.Observable) -> rx.Observable:
    """Fire once, with the triggering ``Health``, when an interlock appears."""
    return health.pipe(
        ops.filter(lambda h: h.interlocks > 0),
        ops.take(1),
    )


# ── orchestrator-neutral event stream ───────────────────────────────────────

@dataclass(frozen=True)
class ScanEvent:
    """One thing that happened during a scan, in a vocabulary no orchestrator
    owns: ``kind`` is one of ``frame | beam_low | beam_ok | interlock``."""
    kind: str
    ts: float
    seq: int
    payload: dict[str, Any] = field(default_factory=dict)


_FRAME_FIELDS = (
    "index", "angle", "counts", "beam_posx", "beam_posy",
    "ring_current", "orbit_x", "quality_ok",
)


def _completion_of(source: rx.Observable) -> rx.Observable:
    """A signal that emits exactly once, the instant *source* completes."""
    return source.pipe(ops.ignore_elements(), ops.default_if_empty(True))


def to_events(frames: rx.Observable, health: rx.Observable) -> rx.Observable:
    """Merge a sweep's frames with beam-health transitions and the interlock
    trigger into one ``ScanEvent`` stream that completes when *frames* does.

    ``frames`` should already be ``share()``-d by the caller if anything else
    also subscribes to it (e.g. a sampled progress feed) — merging two
    independent ``.pipe()`` derivations of the *same* shared source is safe
    and duplicates no PV/attribute I/O; subscribing to two *separate* calls
    of ``sweep_frames`` would not be.

    ``health`` is long-lived and never completes on its own (``ring_health``'s
    poll runs for the whole flow, not just one sweep) — so the beam/interlock
    branches derived from it wouldn't complete either, and a bare
    ``rx.merge`` would then never complete overall (``rx.merge`` only
    completes once *every* source has). ``take_until(_completion_of(frames))``
    is what makes this a per-sweep, not per-flow, event stream: it cuts the
    merge the instant frames finishes, which is always *after* the last frame
    value has already reached every subscriber sharing it — a Subject-backed
    ``share()`` delivers a value to all its observers before it delivers the
    completion that follows it, so nothing is dropped.
    """
    seq = _Counter()

    frame_events = frames.pipe(
        ops.map(lambda f: ScanEvent(
            kind="frame", ts=f[0], seq=seq.next(),
            payload=dict(zip(_FRAME_FIELDS, f[1:])),
        )),
    )

    beam_events = health.pipe(
        ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),
        ops.distinct_until_changed(),
        ops.map(lambda ok: ScanEvent(
            kind="beam_ok" if ok else "beam_low",
            ts=time.time(), seq=seq.next(), payload={},
        )),
    )

    interlock_events = interlock_trigger(health).pipe(
        ops.map(lambda h: ScanEvent(
            kind="interlock", ts=time.time(), seq=seq.next(),
            payload={"interlocks": h.interlocks},
        )),
    )

    return rx.merge(frame_events, beam_events, interlock_events).pipe(
        ops.take_until(_completion_of(frames)),
    )


class _Counter:
    """A plain monotonic counter — ``ScanEvent.seq`` doesn't need to be more
    than a display/ordering aid, so a mutable cell is enough."""

    def __init__(self):
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n


# ── rx-loop → calling-thread boundary ──────────────────────────────────────

def drain(events: rx.Observable, rx_loop, on_event, timeout: float | None = None) -> None:
    """Run *events* to completion, calling ``on_event(ev)`` on the CALLING
    thread — never on the rx loop thread.

    Every orchestrator bridge needs this same boundary. rxepics/rxtango
    subscriptions run on ``RxLoop``'s dedicated asyncio-loop thread (they
    schedule with ``asyncio.ensure_future`` and need a running loop where
    they subscribe), but the side effects a caller wants to attach to each
    event — a Prefect log line or artifact call, an HDF5 write, an SSE
    ``yield`` — must happen on the caller's own thread, which has the run
    context / file handle / response generator the rx loop thread does not.

    So the rx loop thread only ever ``queue.put``s here; this function's own
    thread pulls from the queue and invokes *on_event*. If *on_event*
    raises, the exception propagates out of this call on the calling thread,
    where an orchestrator expects a step to fail (that's how an interlock
    becomes a failed task / errored execution). ``finally`` disposes the
    subscription whether the stream completed, errored, or *on_event* threw.
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


# ── HDF5 run ─────────────────────────────────────────────────────────────────

_DTYPE = np.dtype([
    ("timestamp",    "f8"),
    ("proj_index",   "i4"),
    ("angle",        "f4"),
    ("counts",       "f8"),
    ("beam_posx",    "f4"),
    ("beam_posy",    "f4"),
    ("ring_current", "f4"),   # from Tango
    ("orbit_x",      "f4"),   # from Tango
    ("quality_ok",   "?"),    # derived from Tango orbit
])


class ScanRun:
    """Owns the HDF5 file for one scan run.

    Factored out of ``guarded_scan.py``'s ``main()`` so an orchestrator-side
    task can hold and close it without also owning the acquisition pipeline.
    Same compound dtype and ``projections`` dataset, indexed writes (so an
    aborted run leaves untouched rows zero-filled — ``scan_report.ipynb``
    already keys "acquired" on ``timestamp > 0``).
    """

    def __init__(
        self, out_dir: Path, num_proj: int, exposure_ms: float,
        motor_speed: float, orchestrator: str,
    ):
        self.path = out_dir / f"scan_{orchestrator}_{time.strftime('%Y%m%d_%H%M%S')}.h5"
        self.file = h5py.File(self.path, "w")
        self.dataset = self.file.create_dataset(
            "projections", shape=(num_proj,), dtype=_DTYPE,
        )
        self.file.attrs["exposure_ms"] = exposure_ms
        self.file.attrs["motor_speed"] = motor_speed
        self.file.attrs["num_projections"] = num_proj
        self.file.attrs["orchestrator"] = orchestrator
        # Per-index, not a running tally: a refinement pass (see refine.py)
        # re-acquires a projection and overwrites its row — it must overwrite
        # that row's quality verdict too, not add a second count. The Prefect
        # flow never re-acquires an index, so `frames_written` /
        # `quality_ok_count` read back exactly as before for it.
        self._quality_by_index: dict[int, bool] = {}

    def write_frame(self, frame: tuple) -> None:
        ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality = frame
        self.dataset[i] = (ts, i, angle, counts, bpx, bpy, ring_cur, orbit_x, quality)
        self._quality_by_index[int(i)] = bool(quality)

    @property
    def frames_written(self) -> int:
        return len(self._quality_by_index)

    @property
    def quality_ok_count(self) -> int:
        return sum(1 for ok in self._quality_by_index.values() if ok)

    def close(self) -> None:
        self.file.close()

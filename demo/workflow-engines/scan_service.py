"""Guarded tomography scan — as an HTTP+SSE service, for n8n to orchestrate.

The Prefect demo (``prefect_flow.py``) could hold the scan's live state —
``RxLoop``, the caproto ``Context``, the shared ``health`` observable, the
open ``ScanRun``, the sweep cursor — as plain Python objects passed between
``persist_result=False`` tasks in one process. n8n can't: it has no
in-process Python step (n8n 2.0 replaced the legacy Pyodide node with native
Python on *external task runners*, which is not somewhere you'd run a live
caproto Context and a rxtango event loop at a beamline). Every step is an
HTTP call instead.

So the state becomes a **server-side session** and n8n is left holding only
control flow. This module is that server. It reuses ``scan_core.py``
unchanged (which itself reuses ``../synchrotron-beamline/guarded_scan.py``'s
``guarded_acquire_projection`` unchanged) and adds ``refine.py``'s
quality-driven loop so the n8n graph is a genuine cycle, not a longer DAG:

    POST /scan                         create a session, arm the beamline
    POST /scan/{id}/next               the cursor: what should n8n do next?
    POST /scan/{id}/sweep              acquire the current pass-1 sweep
    POST /scan/{id}/refine             re-acquire the LOW projections
    POST /scan/{id}/wait-healthy       arm auto-resume, return immediately
    POST /scan/{id}/assess             decide: converged? exhausted? keep going?
    POST /scan/{id}/finalize           teardown + summary
    POST /sim/fault                    inject a storage-ring scenario
    GET  /state  /events  /            dashboard snapshot · SSE · the page

Threading: the acquisition endpoints are plain ``def`` (FastAPI runs them in
a worker thread) so they can block inside ``scan_core.drain`` — its
``queue.get`` would stall the event loop in an ``async def``. Only ``/``,
``/state`` and the ``/events`` SSE stream are ``async``.

Run:
    cd ../synchrotron-beamline && docker compose up -d --build
    export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
    python scan_service.py            # :8030
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import reactivex as rx
import reactivex.operators as ops
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import scan_core  # sets sys.path for facility / guarded_scan / rxepics / rxtango
from scan_core import (
    SCAN_ABORTED, SCAN_DONE, ScanEvent, ScanRun, drain, make_context,
    ring_health, scan_setup, scan_teardown, shutter_supervisor, sustained_low,
    sweep_angles, sweep_frames, to_events,
)
from refine import QualityLedger, RefineDecision, assess, refine_points

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "synchrotron-beamline" / "bluesky"))
from rx_bluesky import RxLoop, rx_wait  # noqa: E402

from rx_n8n import EventHub, event_json, resume_on_healthy  # noqa: E402

from facility import (  # noqa: E402
    CONTROLLER, PV_SCAN_CUR_ANGLE, PV_SCAN_STATUS, PV_SHUTTER,
    SCAN_DONE as _SD, SCENARIOS, SCENARIO_NAMES,
)
from rxtango import read_attribute  # noqa: E402
from rxepics.channel import read_pv  # noqa: E402

_HERE = Path(__file__).resolve().parent

_SCAN_STATUS_NAMES = {0: "IDLE", 1: "RUNNING", 2: "DONE", 3: "ABORTED"}


class InterlockAbort(Exception):
    """Raised inside an acquisition when a vacuum-burst interlock appears."""


# ── the session ─────────────────────────────────────────────────────────────

class ScanSession:
    """All of one scan run's live state — the thing that only exists because
    n8n can't carry it between steps itself."""

    def __init__(self, app: FastAPI, params: "CreateScan"):
        self.scan_id = uuid.uuid4().hex[:8]
        self.params = params
        self.total = params.projections

        # shared, service-lifetime resources
        self.rx_loop: RxLoop = app.state.rx_loop
        self.ctx = app.state.ctx
        self.health: rx.Observable = app.state.health
        self.hub: EventHub = app.state.hub

        self.run = ScanRun(
            _HERE, self.total, params.exposure_ms, params.motor_speed,
            orchestrator="n8n",
        )
        self.ledger = QualityLedger(self.total)

        # cursor
        sizes = [len(s) for s in sweep_angles(self.total, params.sweeps,
                                              params.start_angle, params.stop_angle)]
        self.sweep_bounds: list[tuple[int, int]] = []
        lo = 0
        for sz in sizes:
            self.sweep_bounds.append((lo, lo + sz))
            lo += sz
        self._grid = [
            params.start_angle
            + i * (params.stop_angle - params.start_angle) / max(self.total - 1, 1)
            for i in range(self.total)
        ]
        self.index_offset = 0            # next pass-1 projection index
        self.iteration = 1              # 1 = initial full pass; 2+ = refine rounds
        self.assessed_iteration = 0     # last iteration /assess has ruled on
        self.refine_queue: list[tuple[int, float]] = []
        self.last_decision: RefineDecision | None = None

        # lifecycle
        self.outcome = "running"        # running | aborted | completed | converged
        self.abort_reason: str | None = None
        self.finished = False
        self._torn_down = False
        self._file_closed = False
        self.resume_dispose = None
        self.waiting = False           # execution parked at the n8n Wait node
        self.dispose_shutter = None

    # — cursor —

    def current_sweep_range(self) -> tuple[int, int, int] | None:
        """``(sweep_index, lo, hi)`` for the pass-1 sweep that ``index_offset``
        currently sits in, or ``None`` once pass 1 is fully acquired. Works
        mid-sweep too (after a watchdog pause split one sweep in two)."""
        if self.index_offset >= self.total:
            return None
        for k, (lo, hi) in enumerate(self.sweep_bounds):
            if lo <= self.index_offset < hi:
                return (k, lo, hi)
        return None

    def next_action(self) -> dict:
        if self.outcome == "aborted":
            return {"action": "abort", "iteration": self.iteration,
                    "reason": self.abort_reason}

        rng = self.current_sweep_range()
        if self.iteration == 1 and rng is not None:
            k, _lo, hi = rng
            return {
                "action": "sweep", "iteration": 1,
                "sweep_index": k, "sweep_count": len(self.sweep_bounds),
                "index_from": self.index_offset, "index_to": hi,
                "remaining": hi - self.index_offset, "total": self.total,
            }

        if self.iteration > 1 and self.refine_queue:
            return {
                "action": "refine", "iteration": self.iteration,
                "retry_remaining": len(self.refine_queue),
                "retry_indices": [i for i, _ in self.refine_queue],
                "total": self.total,
            }

        if self.assessed_iteration < self.iteration:
            return {"action": "assess", "iteration": self.iteration,
                    "quality_pct": round(self.ledger.quality_pct, 1)}

        d = self.last_decision
        return {
            "action": "done", "iteration": self.iteration,
            "converged": bool(d and d.converged),
            "reason": d.reason if d else "no assessment",
            "quality_pct": round(self.ledger.quality_pct, 1),
            "frames": self.run.frames_written, "total": self.total,
        }

    # — snapshot for the dashboard —

    def snapshot(self) -> dict:
        d = self.last_decision
        phase = self.outcome
        if phase == "running":
            phase = "pass 1" if self.iteration == 1 else f"refine {self.iteration - 1}"
        return {
            "scan_id": self.scan_id,
            "phase": phase,
            "outcome": self.outcome,
            "finished": self.finished,
            "waiting": self.waiting,
            "iteration": self.iteration,
            "max_iterations": self.params.max_iterations,
            "sweep_index": (self.current_sweep_range() or (len(self.sweep_bounds), 0, 0))[0],
            "sweep_count": len(self.sweep_bounds),
            "total": self.total,
            "acquired": self.ledger.acquired_count,
            "quality_ok": self.ledger.ok_count,
            "quality_low": self.ledger.low_count,
            "quality_pct": round(self.ledger.quality_pct, 1),
            "target_quality_pct": self.params.target_quality_pct,
            "retry_indices": self.ledger.retry_indices(),
            "coverage": self.ledger.coverage(),
            "reason": d.reason if d else "",
        }

    # — teardown —

    def mark_aborted(self, reason: str) -> None:
        self.outcome = "aborted"
        self.abort_reason = reason

    def emergency_teardown(self) -> None:
        """Shutter must close now, not after an n8n round-trip."""
        if not self._torn_down:
            rx_wait(scan_teardown(self.ctx, SCAN_ABORTED), self.rx_loop, timeout=15.0)
            self._torn_down = True


# ── acquisition (shared by /sweep and /refine) ─────────────────────────────

def _acquire(session: ScanSession, indices: list[int], angles: list[float]) -> dict:
    """Run one contiguous sweep or one refine batch; block until it completes
    or a watchdog / interlock cuts it short. Same composition as
    ``prefect_flow.run_sweep`` — ``sustained_low`` as the stop trigger,
    ``to_events`` for the interlock, ``drain`` on the calling (worker)
    thread."""
    rx_loop = session.rx_loop
    stop = sustained_low(session.health, session.params.watchdog_s, rx_loop.scheduler)
    frames = sweep_frames(
        session.ctx, session.health, angles, 0, rx_loop.scheduler,
        stop_trigger=stop, indices=indices,
    ).pipe(ops.share())
    combined = to_events(frames, session.health)

    acquired: list[int] = []

    def _on_event(ev: ScanEvent) -> None:
        session.hub.publish(event_json(ev))
        if ev.kind == "frame":
            p = ev.payload
            frame = (
                ev.ts, p["index"], p["angle"], p["counts"],
                p["beam_posx"], p["beam_posy"], p["ring_current"],
                p["orbit_x"], p["quality_ok"],
            )
            session.run.write_frame(frame)
            session.ledger.record_frame(frame)
            acquired.append(int(p["index"]))
        elif ev.kind == "interlock":
            raise InterlockAbort(f"interlocks={ev.payload.get('interlocks')}")

    try:
        drain(combined, rx_loop, _on_event)
    except InterlockAbort as exc:
        session.mark_aborted(str(exc))
        session.emergency_teardown()
        session.hub.publish({"kind": "aborted", "reason": str(exc)})
        return {
            "aborted": True, "reason": str(exc),
            "frames_acquired": len(acquired), "requested": len(angles),
            "watchdog_hit": False,
        }

    return {
        "aborted": False,
        "frames_acquired": len(acquired),
        "acquired_indices": acquired,
        "requested": len(angles),
        "watchdog_hit": len(acquired) < len(angles),
        "quality_ok": session.ledger.ok_count,
        "quality_low": session.ledger.low_count,
        "quality_pct": round(session.ledger.quality_pct, 1),
    }


# ── request models ─────────────────────────────────────────────────────────

class CreateScan(BaseModel):
    projections: int = 36
    sweeps: int = 3
    exposure_ms: float = 30.0
    motor_speed: float = 10.0
    watchdog_s: float = 8.0
    target_quality_pct: float = 95.0
    max_iterations: int = 4
    start_angle: float = 0.0
    stop_angle: float = 180.0


class WaitHealthy(BaseModel):
    resume_url: str


class InjectFault(BaseModel):
    scenario: str


class FinalizeBody(BaseModel):
    status: str | None = None


# ── app / lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    rx_loop = RxLoop()
    ctx = rx_loop.run(make_context())
    health = ring_health(rx_loop.scheduler, interval_ms=1000)

    app.state.rx_loop = rx_loop
    app.state.ctx = ctx
    app.state.health = health
    app.state.hub = EventHub(asyncio.get_running_loop())
    app.state.session = None
    app.state.machine = {
        "current": None, "interlocks": None, "orbit_x": None, "beam_ok": None,
        "scenario": None, "scenario_name": "?", "cur_angle": None,
        "shutter": None, "scan_status": None, "scan_status_name": "?",
        "stale": True, "t": 0,
    }
    _tick = [0]

    def _on_health(h):
        app.state.machine.update(
            current=round(float(h.current), 2),
            interlocks=int(h.interlocks),
            orbit_x=round(float(h.orbit_x), 1),
            beam_ok=bool(h.current >= scan_core.MIN_BEAM_CURRENT and h.interlocks == 0),
            stale=False,
        )
        _tick[0] += 1
        app.state.machine["t"] = _tick[0]

    def _on_extras(t):
        sid = int(t[0])
        app.state.machine.update(
            scenario=sid,
            scenario_name=SCENARIO_NAMES.get(sid, "?"),
            cur_angle=round(float(t[1]), 2),
            shutter=int(t[2]),
            scan_status=int(t[3]),
            scan_status_name=_SCAN_STATUS_NAMES.get(int(t[3]), "?"),
        )

    # anchor the shared ring poll for the whole service lifetime
    anchor1 = rx_loop.subscribe(health, on_next=_on_health,
                                on_error=lambda e: app.state.machine.update(stale=True))
    extras = rx.timer(timedelta(0), timedelta(seconds=1), scheduler=rx_loop.scheduler).pipe(
        ops.flat_map(lambda _: rx.zip(
            read_attribute(CONTROLLER, "ScenarioId"),
            read_pv(PV_SCAN_CUR_ANGLE, ctx),
            read_pv(PV_SHUTTER, ctx),
            read_pv(PV_SCAN_STATUS, ctx),
        ).pipe(ops.catch(lambda _e, _src: rx.empty()))),  # a failed tick is skipped, not fatal
    )
    anchor2 = rx_loop.subscribe(extras, on_next=_on_extras, on_error=lambda e: None)

    try:
        yield
    finally:
        anchor1()
        anchor2()
        sess = app.state.session
        if sess and not sess.finished:
            try:
                if not sess._file_closed:
                    sess.run.close()
            except Exception:
                pass


app = FastAPI(lifespan=lifespan, title="Guarded Tomography Scan — n8n service")


def _require_session(scan_id: str) -> ScanSession:
    sess: ScanSession | None = app.state.session
    if sess is None or sess.scan_id != scan_id:
        raise HTTPException(404, f"no scan {scan_id!r} (one scan at a time)")
    return sess


# ── static + dashboard ────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(_HERE / "scan_dashboard.html")


@app.get("/state")
async def state():
    sess: ScanSession | None = app.state.session
    return JSONResponse({
        "machine": app.state.machine,
        "scan": sess.snapshot() if sess else None,
    })


@app.get("/events")
async def events():
    """SSE feed of every ScanEvent from the running scan (per-frame — the
    continuous view n8n's own per-node output can't give)."""
    return StreamingResponse(
        app.state.hub.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── scan lifecycle ───────────────────────────────────────────────────────

@app.post("/scan")
def create_scan(body: CreateScan, request: Request):
    existing: ScanSession | None = app.state.session
    force = request.query_params.get("force") in ("1", "true", "yes")
    if existing is not None and not existing.finished and not force:
        raise HTTPException(409, f"scan {existing.scan_id} still running "
                                 f"(POST /scan?force=1 to replace)")

    sess = ScanSession(app, body)
    rx_wait(scan_setup(sess.ctx, body.exposure_ms, body.motor_speed),
            sess.rx_loop, timeout=15.0)
    sess.dispose_shutter = sess.rx_loop.subscribe(
        shutter_supervisor(sess.ctx, sess.health), on_next=lambda _ok: None,
    )
    app.state.session = sess
    return {
        "scan_id": sess.scan_id,
        "total": sess.total,
        "sweeps": body.sweeps,
        "target_quality_pct": body.target_quality_pct,
        "max_iterations": body.max_iterations,
        "hdf5": sess.run.path.name,
    }


@app.post("/scan/{scan_id}/next")
def scan_next(scan_id: str):
    return _require_session(scan_id).next_action()


@app.post("/scan/{scan_id}/sweep")
def scan_sweep(scan_id: str):
    sess = _require_session(scan_id)
    rng = sess.current_sweep_range()
    if sess.iteration != 1 or rng is None:
        raise HTTPException(409, "no pass-1 sweep pending — call /next")
    _k, _lo, hi = rng
    indices = list(range(sess.index_offset, hi))
    angles = [sess._grid[i] for i in indices]

    result = _acquire(sess, indices, angles)
    sess.index_offset += result["frames_acquired"]
    result["next_index"] = sess.index_offset
    result["sweep_done"] = sess.index_offset >= hi
    return result


@app.post("/scan/{scan_id}/refine")
def scan_refine(scan_id: str):
    sess = _require_session(scan_id)
    if sess.iteration <= 1 or not sess.refine_queue:
        raise HTTPException(409, "no refine batch pending — call /assess then /next")
    batch = list(sess.refine_queue)
    indices = [i for i, _ in batch]
    angles = [a for _, a in batch]

    result = _acquire(sess, indices, angles)
    done = result["frames_acquired"]
    sess.refine_queue = sess.refine_queue[done:]
    result["retry_remaining"] = len(sess.refine_queue)
    return result


@app.post("/scan/{scan_id}/wait-healthy", status_code=202)
def scan_wait_healthy(scan_id: str, body: WaitHealthy):
    sess = _require_session(scan_id)
    if sess.resume_dispose is not None:
        sess.resume_dispose()
    sess.waiting = True

    def _resumed() -> None:
        sess.waiting = False

    sess.resume_dispose = resume_on_healthy(
        sess.health, sess.rx_loop, body.resume_url, on_resumed=_resumed,
    )
    return {"armed": True, "resume_url": body.resume_url}


@app.post("/scan/{scan_id}/assess")
def scan_assess(scan_id: str):
    sess = _require_session(scan_id)
    if sess.resume_dispose is not None:      # beam is back if we got here
        sess.resume_dispose()
        sess.resume_dispose = None
    sess.waiting = False

    d = assess(
        sess.ledger,
        target_pct=sess.params.target_quality_pct,
        iteration=sess.iteration,
        max_iterations=sess.params.max_iterations,
    )
    sess.last_decision = d
    sess.assessed_iteration = sess.iteration
    if not d.stop:
        sess.iteration += 1
        sess.refine_queue = refine_points(
            d.retry_indices, sess.total, sess.params.start_angle, sess.params.stop_angle,
        )
    return d.as_dict()


@app.post("/scan/{scan_id}/finalize")
def scan_finalize(scan_id: str, body: FinalizeBody | None = None):
    sess = _require_session(scan_id)
    aborted = sess.outcome == "aborted" or (body is not None and body.status == "aborted")

    if not sess._torn_down:
        rx_wait(scan_teardown(sess.ctx, SCAN_ABORTED if aborted else SCAN_DONE),
                sess.rx_loop, timeout=15.0)
        sess._torn_down = True
    if sess.resume_dispose is not None:
        sess.resume_dispose()
        sess.resume_dispose = None
    sess.waiting = False
    if sess.dispose_shutter is not None:
        sess.dispose_shutter()
        sess.dispose_shutter = None
    if not sess._file_closed:
        sess.run.close()
        sess._file_closed = True

    if aborted:
        sess.outcome = "aborted"
    else:
        sess.outcome = "converged" if (sess.last_decision and sess.last_decision.converged) \
            else "completed"
    sess.finished = True

    d = sess.last_decision
    summary = {
        "scan_id": sess.scan_id,
        "outcome": sess.outcome,
        "converged": bool(d and d.converged),
        "reason": (sess.abort_reason if aborted else (d.reason if d else "")),
        "frames_acquired": sess.run.frames_written,
        "total": sess.total,
        "quality_ok": sess.run.quality_ok_count,
        "quality_pct": round(sess.ledger.quality_pct, 1),
        "iterations": sess.iteration,
        "hdf5": sess.run.path.name,
    }
    sess.hub.publish({"kind": "finalized", **summary})
    return summary


# ── fault injection ──────────────────────────────────────────────────────

@app.post("/sim/fault")
def sim_fault(body: InjectFault):
    if body.scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario {body.scenario!r}; "
                                 f"one of {sorted(SCENARIOS)}")
    sid = SCENARIOS[body.scenario]
    rx_wait(read_attribute(CONTROLLER, "ScenarioId"), app.state.rx_loop, timeout=10.0)  # warm
    from rxtango import write_attribute
    rx_wait(write_attribute(CONTROLLER, "ScenarioId", sid), app.state.rx_loop, timeout=10.0)
    return {"scenario": body.scenario, "scenario_id": sid}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("SCAN_SERVICE_HOST", "127.0.0.1"),
        port=int(os.environ.get("SCAN_SERVICE_PORT", "8030")),
        loop="asyncio",   # caproto's UDP search never resolves under uvloop
        log_level="info",
    )

"""Live strip-chart dashboard — the cover image, but real.

A single sliding-window instrument panel for the guarded scan:

  • Beam-current trace (Tango, polled at 5 Hz through rxtango)
  • 50 mA gate line
  • Amber suspension bands — opened when beam_ok goes False, closed on recovery
  • Event-document lane — one tick per acquired projection
  • RunEngine state chips (running / suspended / aborted / done)

Everything is derived from the same PVs/attributes the scan itself mirrors
(SCAN_STATUS, SCAN_CUR_PROJ, SHUTTER, BeamCurrent), so the page works
identically under ../guarded_scan.py and ./guarded_scan_bluesky.py, and does
not touch the scan process.

Usage
-----
    uv run --with fastapi --with "uvicorn[standard]" python live_strip.py
    # open http://127.0.0.1:8010  (STRIP_HOST / STRIP_PORT to override)

Prerequisites: docker stack up + EPICS_CA_* exports (see ../README.md).
"""

import asyncio
import logging
import os
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from facility import (  # noqa: E402
    CONTROLLER, MIN_BEAM_CURRENT,
    PV_SHUTTER, PV_SCAN_STATUS, PV_SCAN_CUR_PROJ, PV_SCAN_CUR_ANGLE,
    PV_DET_COUNTS,
    SCAN_RUNNING,
)
from rxepics.channel import read_pv  # noqa: E402
from rxepics.context import EpicsContext  # noqa: E402
from rxtango import read_attribute  # noqa: E402

log = logging.getLogger(__name__)

POLL_MS   = 200     # 5 Hz — smooth trace, still gentle on the sims
WINDOW_S  = 60.0    # sliding window shown by the client
RETAIN_S  = 75.0    # server-side retention


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx       = await EpicsContext.get()
    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    st = app.state
    st.samples = deque()   # (t, mA)
    st.bands   = []        # {"start": t, "end": t|None} — beam_ok False intervals
    st.events  = deque()   # {"t": t, "proj": int, "angle": float}
    st.live    = {
        "stale": True, "now": 0.0,
        "current": 0.0, "interlocks": 0, "shutter": False,
        "scan_status": 0, "cur_proj": -1, "cur_angle": 0.0, "counts": 0,
        "events_total": 0, "aborted_at": None,
    }
    prev = {"proj": None, "status": None, "beam_ok": None, "stale0": None}

    def ingest(vals) -> None:
        now = time.time()
        current     = float(vals[0])
        interlocks  = int(vals[1])
        shutter     = bool(int(vals[2]))
        scan_status = int(vals[3])
        cur_proj    = int(vals[4])
        cur_angle   = float(vals[5])
        counts      = int(vals[6])

        # trace
        st.samples.append((now, current))
        while st.samples and st.samples[0][0] < now - RETAIN_S:
            st.samples.popleft()

        # suspension bands from beam_ok transitions
        beam_ok = current >= MIN_BEAM_CURRENT
        if prev["beam_ok"] is not None and beam_ok != prev["beam_ok"]:
            if not beam_ok:
                st.bands.append({"start": now, "end": None})
            elif st.bands and st.bands[-1]["end"] is None:
                st.bands[-1]["end"] = now
        st.bands = [b for b in st.bands
                    if b["end"] is None or b["end"] > now - RETAIN_S]

        # event ticks: CUR_PROJ advances while a scan is running.
        # At scan start CUR_PROJ still holds the previous scan's last index —
        # ignore it until the first real event moves it (stale0 guard).
        if scan_status == SCAN_RUNNING and prev["status"] != SCAN_RUNNING:
            st.events.clear()           # a fresh scan begins
            st.live["events_total"] = 0
            st.live["aborted_at"] = None
            prev["stale0"] = cur_proj
        if (scan_status == SCAN_RUNNING and prev["proj"] is not None
                and cur_proj != prev["proj"]):
            st.events.append({"t": now, "proj": cur_proj, "angle": cur_angle})
            prev["stale0"] = None
        if scan_status == SCAN_RUNNING and prev.get("stale0") is None:
            st.live["events_total"] = max(st.live["events_total"], cur_proj + 1)
        while st.events and st.events[0]["t"] < now - RETAIN_S:
            st.events.popleft()

        if scan_status == 3 and prev["status"] != 3:   # ABORTED
            st.live["aborted_at"] = now

        prev.update(proj=cur_proj, status=scan_status, beam_ok=beam_ok)
        st.live.update(
            stale=False, now=now,
            current=round(current, 1), interlocks=interlocks, shutter=shutter,
            scan_status=scan_status, cur_proj=cur_proj,
            proj_valid=not (scan_status == SCAN_RUNNING and prev["stale0"] is not None),
            cur_angle=round(cur_angle, 1), counts=counts,
        )

    def start_poller() -> None:
        def on_error(err):
            log.warning("poller error (%s) — restarting in 2 s", err)
            st.live["stale"] = True
            loop.call_later(2.0, start_poller)

        rx.interval(timedelta(milliseconds=POLL_MS), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: rx.zip(
                read_attribute(CONTROLLER, "BeamCurrent"),      # Tango
                read_attribute(CONTROLLER, "InterlockCount"),   # Tango
                read_pv(PV_SHUTTER, ctx),                       # EPICS
                read_pv(PV_SCAN_STATUS, ctx),
                read_pv(PV_SCAN_CUR_PROJ, ctx),
                read_pv(PV_SCAN_CUR_ANGLE, ctx),
                read_pv(PV_DET_COUNTS, ctx),
            )),
        ).subscribe(on_next=ingest, on_error=on_error, scheduler=scheduler)

    start_poller()
    yield
    EpicsContext.close()


app = FastAPI(lifespan=lifespan, title="Guarded Scan — Live Strip")
_HERE = Path(__file__).parent


@app.get("/")
async def index():
    return FileResponse(_HERE / "strip.html")


@app.get("/state")
async def state():
    st = app.state
    return JSONResponse({
        **st.live,
        "window_s": WINDOW_S,
        "gate": MIN_BEAM_CURRENT,
        "samples": [[round(t, 3), round(v, 2)] for t, v in st.samples],
        "bands": st.bands,
        "events": list(st.events),
    })


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("STRIP_HOST", "127.0.0.1")
    port = int(os.environ.get("STRIP_PORT", "8010"))
    # loop="asyncio": caproto's UDP search does not come up under uvloop
    uvicorn.run(app, host=host, port=port, log_level="warning", loop="asyncio")

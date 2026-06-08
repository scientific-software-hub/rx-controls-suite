"""FastAPI live dashboard for the synchrotron-beamline demo.

Polls the storage ring (Tango) and tomography beamline (EPICS) at 1 Hz using
the existing reactive wrappers, caches the latest snapshot, and serves it as
JSON so the browser can animate the SVG dashboard without reloading the page.

Usage
-----
    uv run --with fastapi --with "uvicorn[standard]" python live_dashboard.py
    # then open http://127.0.0.1:8000

Environment
-----------
    DASHBOARD_HOST   bind address (default: 127.0.0.1)
    DASHBOARD_PORT   port (default: 8000)

Prerequisites
-------------
    docker compose up -d --build           (ring + IOC + sim)
    export EPICS_CA_AUTO_ADDR_LIST=NO      (every client shell)
    export EPICS_CA_ADDR_LIST=127.0.0.1
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

# ── path bootstrap (mirrors facility.py) ─────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute
from rxepics.channel import read_pv
from rxepics.context import EpicsContext

from facility import (
    CONTROLLER,
    PV_ROT_VAL, PV_ROT_MOVN, PV_DET_COUNTS, PV_DET_ACQUIRING,
    PV_BEAM_POSX, PV_BEAM_POSY, PV_SHUTTER, PV_SCAN_STATUS,
    PV_SCAN_CUR_PROJ, PV_SCAN_CUR_ANGLE,
    MIN_BEAM_CURRENT, ORBIT_ALARM,
    SCAN_IDLE, SCAN_RUNNING, SCAN_DONE, SCAN_ABORTED,
    Health, is_healthy,
)

log = logging.getLogger(__name__)

# ── device addresses ──────────────────────────────────────────────────────────
# CONTROLLER = "tango://localhost:10000/sr/demo/controller"
# Strip the device part to get "tango://localhost:10000"
_TANGO_BASE = "/".join(CONTROLLER.split("/")[:3])
SECTORS = [f"{_TANGO_BASE}/sr/demo/sector{i:02d}" for i in range(1, 9)]

_CTRL_ATTRS  = ["BeamCurrent", "InterlockCount", "LifetimeHours", "ScenarioId"]
_SECTOR_ATTRS = ["OrbitX", "VacuumPressure", "RadiationDoseRate", "BeamLossFraction"]
_EPICS_PVS = [
    PV_ROT_VAL, PV_ROT_MOVN, PV_DET_COUNTS, PV_DET_ACQUIRING,
    PV_BEAM_POSX, PV_BEAM_POSY, PV_SHUTTER, PV_SCAN_STATUS,
    PV_SCAN_CUR_PROJ, PV_SCAN_CUR_ANGLE,
]

SCENARIO_NAMES = {
    0: "nominal",
    1: "orbit_drift",
    2: "vacuum_burst",
    3: "beam_loss",
}
SCAN_STATUS_NAMES = {
    SCAN_IDLE:    "idle",
    SCAN_RUNNING: "running",
    SCAN_DONE:    "done",
    SCAN_ABORTED: "aborted",
}

# ── initial (connecting) snapshot ─────────────────────────────────────────────
_INITIAL_SNAPSHOT: dict = {
    "stale": True,
    "t": 0,
    "ring": {
        "current": 0.0, "interlocks": 0, "lifetime": 0.0,
        "scenario_id": 0, "scenario": "nominal",
        "healthy": False, "beam_low": True, "status": "connecting",
    },
    "sectors": [
        {
            "index": i + 1,
            "orbit_x": 0.0, "vacuum": 0.0, "radiation": 0.0, "loss": 0.0,
            "orbit_alarm": False, "vacuum_alarm": False,
            "radiation_alarm": False, "alarm": False,
        }
        for i in range(8)
    ],
    "beamline": {
        "angle": 0.0, "moving": False,
        "counts": 0, "acquiring": False,
        "beam_x": 0.0, "beam_y": 0.0,
        "shutter": False,
        "scan_status": SCAN_IDLE, "scan_status_name": "idle",
        "cur_proj": 0, "cur_angle": 0.0,
    },
}


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start 1 Hz reactive poller on startup; clean up on shutdown."""
    ctx       = await EpicsContext.get()
    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    app.state.snapshot = dict(_INITIAL_SNAPSHOT)
    tick = [0]   # mutable counter captured by build_snapshot closure

    # ── observable factories ──────────────────────────────────────────────────

    def make_reads():
        """Build one rx.zip of all 46 reads for a single poll tick.

        Layout of the emitted tuple (used by build_snapshot):
          [0..3]   controller: BeamCurrent, InterlockCount, LifetimeHours, ScenarioId
          [4..35]  sectors 1–8, 4 values each: OrbitX, VacuumPressure,
                   RadiationDoseRate, BeamLossFraction
          [36..45] EPICS: ROT_VAL, ROT_MOVN, DET_COUNTS, DET_ACQUIRING,
                   BEAM_POSX, BEAM_POSY, SHUTTER, SCAN_STATUS,
                   SCAN_CUR_PROJ, SCAN_CUR_ANGLE
        """
        ctrl_reads = [read_attribute(CONTROLLER, a) for a in _CTRL_ATTRS]
        sector_reads = [
            read_attribute(sector, attr)
            for sector in SECTORS
            for attr in _SECTOR_ATTRS
        ]
        epics_reads = [read_pv(pv, ctx) for pv in _EPICS_PVS]
        return rx.zip(*ctrl_reads, *sector_reads, *epics_reads)

    def build_snapshot(vals) -> dict:
        """Map the flat 46-element tuple to a structured snapshot dict."""
        # controller
        current     = float(vals[0])
        interlocks  = int(vals[1])
        lifetime    = float(vals[2])
        scenario_id = int(vals[3])

        # sectors (4 values × 8 sectors = indices 4..35)
        sectors = []
        for i in range(8):
            base      = 4 + i * 4
            orbit_x   = float(vals[base])
            vacuum    = float(vals[base + 1])
            radiation = float(vals[base + 2])
            loss      = float(vals[base + 3])
            vac_alarm = vacuum    >= 1.55
            rad_alarm = radiation >= 1.10
            orb_alarm = abs(orbit_x) >= ORBIT_ALARM
            sectors.append({
                "index":           i + 1,
                "orbit_x":         round(orbit_x, 2),
                "vacuum":          round(vacuum, 3),
                "radiation":       round(radiation, 3),
                "loss":            round(loss, 3),
                "orbit_alarm":     orb_alarm,
                "vacuum_alarm":    vac_alarm,
                "radiation_alarm": rad_alarm,
                "alarm":           orb_alarm or vac_alarm or rad_alarm,
            })

        # ring-level health (reuse facility.py semantics)
        h        = Health(current=current, interlocks=interlocks,
                          orbit_x=sectors[3]["orbit_x"])  # sector04 = idx 3
        healthy  = is_healthy(h)
        beam_low = current < MIN_BEAM_CURRENT
        if interlocks > 0:
            status = "interlock"
        elif beam_low:
            status = "beam-low"
        else:
            status = "healthy"

        # EPICS beamline (indices 36..45)
        ep          = vals[36:]
        angle       = float(ep[0])
        moving      = bool(int(ep[1]))
        counts      = int(ep[2])
        acquiring   = bool(int(ep[3]))
        beam_x      = float(ep[4])
        beam_y      = float(ep[5])
        shutter     = bool(int(ep[6]))
        scan_status = int(ep[7])
        cur_proj    = int(ep[8])
        cur_angle   = float(ep[9])

        tick[0] += 1
        return {
            "stale": False,
            "t":     tick[0],
            "ring": {
                "current":     round(current, 1),
                "interlocks":  interlocks,
                "lifetime":    round(lifetime, 2),
                "scenario_id": scenario_id,
                "scenario":    SCENARIO_NAMES.get(scenario_id, "unknown"),
                "healthy":     healthy,
                "beam_low":    beam_low,
                "status":      status,
            },
            "sectors": sectors,
            "beamline": {
                "angle":            round(angle, 1),
                "moving":           moving,
                "counts":           counts,
                "acquiring":        acquiring,
                "beam_x":           round(beam_x, 2),
                "beam_y":           round(beam_y, 2),
                "shutter":          shutter,
                "scan_status":      scan_status,
                "scan_status_name": SCAN_STATUS_NAMES.get(scan_status, "unknown"),
                "cur_proj":         cur_proj,
                "cur_angle":        round(cur_angle, 1),
            },
        }

    # ── poller lifecycle ──────────────────────────────────────────────────────

    def start_poller():
        """Create and subscribe to the 1 Hz polling stream.

        On error: logs a warning, marks the snapshot stale, and schedules a
        restart in 2 s so transient connection blips don't kill the dashboard.
        """
        def cache(snapshot):
            app.state.snapshot = snapshot

        def on_error(err):
            log.warning("poller error (%s) — restarting in 2 s", err)
            app.state.snapshot = {**app.state.snapshot, "stale": True}
            loop.call_later(2.0, start_poller)

        rx.interval(timedelta(seconds=1), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: make_reads()),
            ops.map(build_snapshot),
        ).subscribe(
            on_next=cache,
            on_error=on_error,
            scheduler=scheduler,
        )

    start_poller()
    yield
    EpicsContext.close()


app = FastAPI(lifespan=lifespan, title="Synchrotron Beamline Dashboard")

_HERE = Path(__file__).parent


@app.get("/")
async def index():
    """Serve the static SVG dashboard page."""
    return FileResponse(_HERE / "dashboard.html")


@app.get("/state")
async def state():
    """Return the latest polled snapshot as JSON."""
    return JSONResponse(app.state.snapshot)


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")

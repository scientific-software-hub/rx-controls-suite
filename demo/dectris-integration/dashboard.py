"""RxDECTRIS live dashboard — FACILITY | DETECTOR | D.LAB.

Polls all three services directly (facility health via the same rx primitive
``experiment.py`` uses, detector/D.LAB via their ``/_sim/*`` status
endpoints) and has no coupling to the experiment process itself — it renders
correctly before, during, and after a run, and survives ``experiment.py``
being restarted mid-demo.

Run:
    uv run --with fastapi --with "uvicorn[standard]" python dashboard.py
    -> http://localhost:8020

Env: DASHBOARD_HOST (default 127.0.0.1), DASHBOARD_PORT (default 8020),
SIMPLON_URL (default http://localhost:8080), DLAB_URL (default
http://localhost:8090).
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from reactivex.scheduler.eventloop import AsyncIOScheduler

from facilities import TangoFacility  # noqa: E402  -- the Tango-native ring; see module docstring

POLL_MS = 500
SIMPLON_URL = os.environ.get("SIMPLON_URL", "http://localhost:8080")
DLAB_URL = os.environ.get("DLAB_URL", "http://localhost:8090")

_INITIAL_SNAPSHOT = {
    "stale": True,
    "facility": {"beam_available": False, "interlock_ok": True, "orbit_ok": True, "current": None},
    "detector": {"state": "na", "image_id": -1, "number_of_images": 0},
    "dlab": {"job_id": None, "status": None, "error": None},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    app.state.snapshot = dict(_INITIAL_SNAPSHOT)
    app.state.http = httpx.AsyncClient(timeout=3.0)

    # The dashboard shows the underlying simulated ring's health directly via
    # Tango — it's the same physical machine EpicsFacility mirrors, and the
    # dashboard doesn't need to know which --facility a running experiment
    # picked to render a truthful picture of it.
    facility = TangoFacility(scheduler, interval_ms=POLL_MS)

    def cache_facility(h) -> None:
        app.state.snapshot["facility"] = {
            "beam_available": h.beam_available,
            "interlock_ok": h.interlock_ok,
            "orbit_ok": h.orbit_ok,
            "current": h.current,
        }
        app.state.snapshot["stale"] = False

    facility.health().subscribe(on_next=cache_facility, on_error=lambda e: None, scheduler=scheduler)

    async def poll_http() -> None:
        while True:
            try:
                resp = await app.state.http.get(f"{SIMPLON_URL}/_sim/progress")
                app.state.snapshot["detector"] = resp.json()
            except Exception:
                app.state.snapshot["detector"] = {"state": "unreachable", "image_id": -1, "number_of_images": 0}
            try:
                resp = await app.state.http.get(f"{DLAB_URL}/_sim/latest_job")
                app.state.snapshot["dlab"] = resp.json()
            except Exception:
                app.state.snapshot["dlab"] = {"job_id": None, "status": "unreachable", "error": None}
            await asyncio.sleep(POLL_MS / 1000)

    poll_task = asyncio.ensure_future(poll_http())
    yield
    poll_task.cancel()
    await app.state.http.aclose()


app = FastAPI(title="RxDECTRIS dashboard", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(_HERE / "index.html")


@app.get("/state")
async def state():
    return JSONResponse(app.state.snapshot)


if __name__ == "__main__":
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8020"))
    uvicorn.run(app, host=host, port=port, log_level="warning", loop="asyncio")

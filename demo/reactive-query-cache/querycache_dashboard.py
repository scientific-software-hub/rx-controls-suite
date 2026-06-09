"""FastAPI backend for the Reactive Query Cache demo.

Architecture
------------
Each frontend component opens its own SSE stream via ``GET /subscribe?keys=a,b,c``.
The backend's ``QueryCache`` merges all requests for the same key into
**one** upstream Tango / EPICS read per key — no matter how many components
are subscribed.

The headline ``GET /metrics/stream`` SSE pushes the cache's internal metrics
every 500 ms so the Cache-Inspector panel in ``index.html`` can show:

    14 component subs  →  8 upstream SCADA subs    (ops/sec stays flat)

Transport note — SSE vs. WebSocket
-----------------------------------
One ``EventSource`` per component is the simplest transport: stateless,
auto-reconnecting, native browser support, trivial server implementation.

**Limitation:** browsers cap HTTP/1.1 connections to the same host at 6.
This demo uses 1 connection for ``/metrics/stream`` (inspector) plus 1 per
component, so you can have ~5 components before new ones stall silently.

**When to switch to WebSocket:** if you need more than ~5 concurrent
components in the same browser tab, replace per-component ``EventSource``
connections with a single ``WebSocket /ws`` endpoint that multiplexes all
component subscriptions over one TCP connection via JSON messages
``{action:"subscribe", component_id, keys}`` / ``{action:"unsubscribe", …}``.
The ``QueryCache`` logic is completely unchanged — only the transport layer
differs.  HTTP/2 (requires TLS in browsers) is another option.

Query keys exposed
------------------
Ring (Tango / sr/demo/controller + sector04):
    ring.current        BeamCurrent  [mA]
    ring.interlocks     InterlockCount
    ring.lifetime       LifetimeHours  [h]
    ring.scenario_id    ScenarioId (0=nominal, 1=orbit_drift, 2=vacuum_burst, 3=beam_loss)
    sector04.orbit_x    OrbitX  [µm]
    sector04.vacuum     VacuumPressure  [mbar]
    sector04.radiation  RadiationDoseRate  [mGy/h]

Beamline (EPICS):
    beam.angle          TOMO:ROT:VAL    rotation angle  [°]
    beam.shutter        TOMO:SHUTTER:OPEN   0/1
    beam.counts         TOMO:DET:COUNTS

Usage
-----
    # from demo/reactive-query-cache/
    uv run --with fastapi --with "uvicorn[standard]" python querycache_dashboard.py
    # then open http://127.0.0.1:8000

Prerequisites
-------------
    docker compose -f ../synchrotron-beamline/docker-compose.yml up -d --build
    export EPICS_CA_AUTO_ADDR_LIST=NO
    export EPICS_CA_ADDR_LIST=127.0.0.1
"""

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ── path bootstrap (mirrors live_dashboard.py) ────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))
# reuse constants from the sibling demo — no duplication
sys.path.insert(0, str(_ROOT / "demo" / "synchrotron-beamline"))

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute
from rxepics.channel import read_pv
from rxepics.context import EpicsContext

from facility import (
    CONTROLLER, SECTOR_04,
    PV_ROT_VAL, PV_SHUTTER, PV_DET_COUNTS,
)
from query_cache import QueryCache

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

# ── poll interval ─────────────────────────────────────────────────────────────
POLL_MS   = 1_000   # 1 Hz — same as the sibling live_dashboard
STALE_MS  = 5_000   # a cached value older than 5 s is tagged stale
GC_MS     = 10_000  # disconnect upstream 10 s after last observer leaves


# ── source catalog ────────────────────────────────────────────────────────────
# Each entry is a *factory* that creates a cold polling Observable.
# The lambda is called at most once per key while the upstream is live.

def _make_sources(scheduler, ctx) -> dict:
    """Build the key → source-factory mapping.

    All sources follow the same pattern as facility.ring_health():
        rx.interval(POLL_MS) → flat_map(single-shot read) → map(cast)
    This makes the upstream load metric transparent: ops/sec = active_keys / s.
    """
    def tango_poller(device: str, attr: str, cast=float):
        return rx.interval(timedelta(milliseconds=POLL_MS), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_attribute(device, attr)),
            ops.map(cast),
        )

    def epics_poller(pv: str, cast=float):
        return rx.interval(timedelta(milliseconds=POLL_MS), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_pv(pv, ctx)),
            ops.map(cast),
        )

    return {
        # ── ring (Tango) ──────────────────────────────────────────────────────
        "ring.current":       lambda: tango_poller(CONTROLLER, "BeamCurrent",     float),
        "ring.interlocks":    lambda: tango_poller(CONTROLLER, "InterlockCount",  int),
        "ring.lifetime":      lambda: tango_poller(CONTROLLER, "LifetimeHours",   float),
        "ring.scenario_id":   lambda: tango_poller(CONTROLLER, "ScenarioId",      int),
        "sector04.orbit_x":   lambda: tango_poller(SECTOR_04,  "OrbitX",          float),
        "sector04.vacuum":    lambda: tango_poller(SECTOR_04,  "VacuumPressure",  float),
        "sector04.radiation": lambda: tango_poller(SECTOR_04,  "RadiationDoseRate", float),
        # ── beamline (EPICS) ──────────────────────────────────────────────────
        "beam.angle":         lambda: epics_poller(PV_ROT_VAL,  float),
        "beam.shutter":       lambda: epics_poller(PV_SHUTTER,  int),
        "beam.counts":        lambda: epics_poller(PV_DET_COUNTS, int),
    }


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise EPICS context + QueryCache on startup; tear down on shutdown."""
    ctx       = await EpicsContext.get()
    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    sources = _make_sources(scheduler, ctx)

    def source_factory(key: str) -> rx.Observable:
        factory = sources.get(key)
        if factory is None:
            log.warning("QueryCache: unknown key %r — emitting empty Observable", key)
            return rx.empty()
        return factory()

    cache = QueryCache(
        scheduler,
        source_factory,
        poll_ms=POLL_MS,
        stale_ms=STALE_MS,
        gc_ms=GC_MS,
    )

    app.state.cache     = cache
    app.state.scheduler = scheduler

    log.info("QueryCache ready — %d keys in catalog", len(sources))
    yield
    cache.close()
    EpicsContext.close()
    log.info("QueryCache closed")


app = FastAPI(lifespan=lifespan, title="Reactive Query Cache Demo")


# ── static ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    """Serve the multi-component dashboard."""
    return FileResponse(_HERE / "index.html")


# ── per-component SSE stream ──────────────────────────────────────────────────

@app.get("/subscribe")
async def subscribe(request: Request, keys: str = ""):
    """Per-component SSE stream.

    Each frontend component opens its own EventSource to this endpoint,
    declaring the keys it needs.  The QueryCache merges all requests for
    the same key into one upstream subscription — this endpoint is where
    the dedup story plays out.

    **Browser connection limit:** HTTP/1.1 allows ~6 concurrent connections
    per host.  With the /metrics/stream inspector connection always open,
    this means roughly 5 components per browser tab before new ones stall.
    See the module docstring for the WebSocket upgrade path.

    Query params
    ------------
    keys : comma-separated query key names, e.g. ``ring.current,ring.interlocks``
    """
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    if not key_list:
        return JSONResponse({"error": "no keys requested"}, status_code=400)

    cache:     QueryCache = request.app.state.cache
    scheduler             = request.app.state.scheduler

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        disposables = []

        for key in key_list:
            # Closure must capture the key by value — use a default arg.
            def make_handler(k: str):
                def on_next(value):
                    try:
                        queue.put_nowait({"key": k, "value": value, "ts": time.time()})
                    except asyncio.QueueFull:
                        pass   # slow client — drop rather than block Rx
                return on_next

            d = cache.observe(key).subscribe(
                on_next=make_handler(key),
                scheduler=scheduler,
            )
            disposables.append(d)

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    # keepalive comment — prevents proxy / browser from closing
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            for d in disposables:
                try:
                    d.dispose()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── cache metrics SSE stream ──────────────────────────────────────────────────

@app.get("/metrics/stream")
async def metrics_stream():
    """Server-Sent Events stream of QueryCache metrics at ~2 Hz.

    Consumed by the Cache-Inspector panel in index.html to show the
    live component-sub → upstream-sub gauge.
    """
    cache: QueryCache = app.state.cache

    async def gen():
        try:
            while True:
                payload = json.dumps(cache.metrics())
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)
        except GeneratorExit:
            pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/metrics")
async def metrics_json():
    """One-shot JSON snapshot of cache state — handy for curl debugging."""
    return JSONResponse(app.state.cache.metrics())


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")

"""SIMPLON-shaped FastAPI simulator — HTTP subsystems + Stream V2 (ZeroMQ/CBOR) push.

Run:
    uv run --with fastapi --with "uvicorn[standard]" --with pyzmq --with cbor2 \\
        python app.py

Env: SIMPLON_HOST (default 0.0.0.0), SIMPLON_PORT (default 8080),
     SIMPLON_STREAM_PORT (default 31001).

Endpoints are grouped by SIMPLON module (detector / stream / monitor) plus a
``/_sim/*`` namespace for the demo's own controls (fault injection, progress
polling for the dashboard) — none of which shadow real SIMPLON paths.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import cbor2
import uvicorn
import zmq
import zmq.asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from state import DetectorSim, SimError

API_VERSION = "1.8.0"
STREAM_PORT = int(os.environ.get("SIMPLON_STREAM_PORT", "31001"))


class MonitorBuffer:
    """The Monitor subsystem's FIFO — separate from the Stream V2 socket.

    Mirrors ``discard_new``: True (default) drops the incoming frame when
    full; False evicts the oldest frame to make room, matching SIMPLON 1.8
    API documentation §5.2.1.
    """

    def __init__(self, sim: DetectorSim) -> None:
        self._sim = sim
        self._buf: list[dict] = []

    def push(self, frame: dict) -> None:
        if self._sim.monitor_config["mode"]["value"] != "enabled":
            return
        size = int(self._sim.monitor_config["buffer_size"]["value"])
        if len(self._buf) >= size:
            if bool(self._sim.monitor_config["discard_new"]["value"]):
                return
            self._buf.pop(0)
        self._buf.append(frame)

    def pop_next(self) -> dict | None:
        return self._buf.pop(0) if self._buf else None

    def peek_latest(self) -> dict | None:
        return self._buf[-1] if self._buf else None

    def fill_level(self) -> list[int]:
        size = int(self._sim.monitor_config["buffer_size"]["value"])
        return [len(self._buf), size]


@asynccontextmanager
async def lifespan(app: FastAPI):
    zmq_ctx = zmq.asyncio.Context()
    push_socket = zmq_ctx.socket(zmq.PUSH)
    # A PUSH socket round-robins across every peer that has ever connected,
    # including ones that vanished without a clean disconnect (every demo
    # script here opens a fresh TCP connection per process and never closes
    # it). Without a send timeout, one dead peer's full queue can block
    # *every* subsequent emit() — including the command handlers that call
    # it — hanging the whole detector, not just the stream. SNDTIMEO turns
    # that into a drop instead of a hang.
    push_socket.setsockopt(zmq.SNDTIMEO, 1000)
    push_socket.bind(f"tcp://*:{STREAM_PORT}")

    async def emit(message: dict) -> None:
        try:
            await push_socket.send(cbor2.dumps(message))
        except zmq.Again:
            pass  # no consumer draining fast enough right now — drop, don't hang

    sim_holder: dict = {}

    def on_monitor_frame(frame: dict) -> None:
        sim_holder["monitor"].push(frame)

    sim = DetectorSim(emit=emit, on_monitor_frame=on_monitor_frame)
    monitor = MonitorBuffer(sim)
    sim_holder["monitor"] = monitor

    app.state.sim = sim
    app.state.monitor = monitor

    yield

    push_socket.close(linger=0)
    zmq_ctx.term()


app = FastAPI(title="simplon_sim", lifespan=lifespan)


def _err(exc: SimError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Detector — config
# ---------------------------------------------------------------------------


@app.get("/detector/api/{version}/config/{parameter}")
async def get_detector_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    try:
        return sim.read_config(sim.detector_config, parameter)
    except SimError as exc:
        return _err(exc)


@app.put("/detector/api/{version}/config/{parameter}")
async def put_detector_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    body = await request.json()
    try:
        return sim.write_config(sim.detector_config, parameter, body["value"])
    except SimError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Detector — status
# ---------------------------------------------------------------------------


@app.get("/detector/api/{version}/status/{parameter:path}")
async def get_detector_status(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    try:
        value = sim.read_status(parameter)
        return {"value": value}
    except SimError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Detector — commands
# ---------------------------------------------------------------------------


@app.put("/detector/api/{version}/command/{name}")
async def put_detector_command(version: str, name: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    body = {}
    if request.headers.get("content-length", "0") != "0":
        try:
            body = await request.json()
        except Exception:
            body = {}
    try:
        if name == "initialize":
            await sim.initialize()
            return Response(status_code=200)
        if name == "arm":
            seq = await sim.arm()
            return {"sequence_id": seq}
        if name == "trigger":
            await sim.trigger(count_time_override=body.get("value"))
            return Response(status_code=200)
        if name == "disarm":
            seq = await sim.disarm()
            return {"sequence_id": seq}
        if name == "abort":
            seq = await sim.abort()
            return {"sequence_id": seq}
        if name == "cancel":
            seq = await sim.cancel()
            return {"sequence_id": seq}
        return JSONResponse(status_code=404, content={"error": f"unknown command: {name}"})
    except SimError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Stream — config
# ---------------------------------------------------------------------------


@app.get("/stream/api/{version}/config/{parameter}")
async def get_stream_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    try:
        return sim.read_config(sim.stream_config, parameter)
    except SimError as exc:
        return _err(exc)


@app.put("/stream/api/{version}/config/{parameter}")
async def put_stream_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    body = await request.json()
    try:
        return sim.write_config(sim.stream_config, parameter, body["value"])
    except SimError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Monitor — config, status, data access
# ---------------------------------------------------------------------------


@app.get("/monitor/api/{version}/config/{parameter}")
async def get_monitor_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    try:
        return sim.read_config(sim.monitor_config, parameter)
    except SimError as exc:
        return _err(exc)


@app.put("/monitor/api/{version}/config/{parameter}")
async def put_monitor_config(version: str, parameter: str, request: Request):
    sim: DetectorSim = request.app.state.sim
    body = await request.json()
    try:
        return sim.write_config(sim.monitor_config, parameter, body["value"])
    except SimError as exc:
        return _err(exc)


@app.get("/monitor/api/{version}/status/buffer_fill_level")
async def get_buffer_fill_level(version: str, request: Request):
    monitor: MonitorBuffer = request.app.state.monitor
    return {"value": monitor.fill_level()}


@app.get("/monitor/api/{version}/images/{mode}")
async def get_monitor_image(version: str, mode: str, request: Request, timeout: int = 200):
    monitor: MonitorBuffer = request.app.state.monitor
    if mode == "next":
        frame = monitor.pop_next()
    elif mode == "monitor":
        frame = monitor.peek_latest()
    else:
        return JSONResponse(status_code=404, content={"error": f"unknown monitor image parameter: {mode}"})
    if frame is None:
        return Response(status_code=408)  # SIMPLON: no image available within ?timeout=
    return frame


# ---------------------------------------------------------------------------
# Demo-only controls — namespaced so nothing shadows a real SIMPLON path
# ---------------------------------------------------------------------------


@app.put("/_sim/fault")
async def put_fault(request: Request):
    sim: DetectorSim = request.app.state.sim
    body = await request.json()
    sim.set_fault(body["value"])
    return {"fault": body["value"]}


@app.get("/_sim/progress")
async def get_progress(request: Request):
    sim: DetectorSim = request.app.state.sim
    return {"state": sim.state, **sim.progress}


if __name__ == "__main__":
    host = os.environ.get("SIMPLON_HOST", "0.0.0.0")
    port = int(os.environ.get("SIMPLON_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="warning", loop="asyncio")

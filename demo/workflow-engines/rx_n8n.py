"""Rx ↔ n8n bridge.

Parallel to ``rx_prefect.py``'s five adapters, this module is n8n's three:

    event_json          one ScanEvent        →  a JSON-safe dict (SSE / logs)
    EventHub            ScanEvent stream     →  fan-out to N live SSE clients
    resume_on_healthy   health recovery      →  POST n8n's $execution.resumeUrl

Why this bridge is *shorter* than the Prefect one
-------------------------------------------------
``rx_prefect.py``'s hardest adapter is ``pause_until_healthy``: it has to hop
the resume call onto a private ``ThreadPoolScheduler(1)`` because Prefect's
``resume_flow_run`` is wrapped in ``@async_dispatch``, which sniffs
``asyncio.get_running_loop()`` and silently no-ops (returns an unawaited
coroutine) when it runs on the rx loop thread — which always *has* a running
loop.

n8n has no such thing. Resuming a waiting execution is a plain
``POST <resumeUrl>`` — an HTTP request with no thread-local run context to
respect. ``resume_on_healthy`` fires it straight from the rx ``on_next`` via
``run_coroutine_threadsafe`` onto the rx loop (which is a real asyncio loop),
so the POST never blocks the callback and needs no worker thread. That
difference — *the orchestrator boundary is an HTTP call, not an in-process
SDK with hidden context* — is one of the findings this demo exists to show,
not an accident of implementation.

The other structural consequence lives in ``scan_service.py``: because every
step is a separate HTTP request, the scan's state (``rx_loop``, caproto
``ctx``, the shared ``health`` observable, the open ``ScanRun``, the
``QualityLedger``, the sweep/iteration cursor) can't be passed between steps
as Python objects the way Prefect passes them between ``persist_result=False``
tasks. It has to become a server-side session. n8n is left holding only
control flow.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Iterable

import httpx
import reactivex as rx
import reactivex.operators as ops

from scan_core import ScanEvent, is_healthy


# ── ScanEvent → JSON-safe dict ─────────────────────────────────────────────

_FRAME_KEYS = (
    "index", "angle", "counts", "beam_posx", "beam_posy",
    "ring_current", "orbit_x", "quality_ok",
)


def event_json(ev: ScanEvent) -> dict[str, Any]:
    """One ``ScanEvent`` → a dict that ``json.dumps`` accepts.

    caproto/PyTango hand back numpy scalars; coerce every frame field to a
    plain ``float`` / ``int`` / ``bool`` so both the SSE feed and any n8n
    node that echoes the payload stay clean.
    """
    out: dict[str, Any] = {"kind": ev.kind, "ts": float(ev.ts), "seq": int(ev.seq)}
    if ev.kind == "frame":
        p = ev.payload
        out["frame"] = {
            "index": int(p["index"]),
            "angle": round(float(p["angle"]), 3),
            "counts": float(p["counts"]),
            "beam_posx": float(p["beam_posx"]),
            "beam_posy": float(p["beam_posy"]),
            "ring_current": float(p["ring_current"]),
            "orbit_x": float(p["orbit_x"]),
            "quality_ok": bool(p["quality_ok"]),
        }
    elif ev.kind == "interlock":
        out["interlocks"] = int(ev.payload.get("interlocks", 0))
    return out


# ── ScanEvent stream → N live SSE clients ──────────────────────────────────

class EventHub:
    """A per-service fan-out from the acquisition threads to any number of
    connected ``text/event-stream`` clients (the dashboard).

    ``publish`` is safe to call from any thread — it marshals onto the
    uvicorn event loop with ``call_soon_threadsafe`` before touching the
    subscriber queues. A slow client's full queue drops items rather than
    blocking the acquisition, exactly as ``querycache_dashboard.py`` does.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._subs: set[asyncio.Queue] = set()

    def publish(self, item: dict) -> None:
        self._loop.call_soon_threadsafe(self._fanout, item)

    def _fanout(self, item: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass

    async def stream(self, keepalive_s: float = 15.0):
        """Async generator of SSE frames for one client. Registers a queue,
        yields ``data:``/keepalive lines, and always unregisters on exit."""
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=keepalive_s)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:  # client hung up
            raise
        finally:
            self._subs.discard(q)


# ── beam recovery → resume the waiting n8n execution ──────────────────────

def resume_on_healthy(health: rx.Observable, rx_loop, resume_url: str, on_resumed=None):
    """Arm a one-shot: the instant the ring is healthy again, call the n8n
    resume URL so the waiting ``Wait`` node continues, then invoke
    *on_resumed* (used to clear the session's ``waiting`` flag).

    Returns a zero-arg dispose. The caller (``/scan/{id}/wait-healthy``)
    stores it and disposes it once the execution has resumed — whether via
    this call or a manual resume from the n8n UI — so a stray subscription
    doesn't outlive the pause.

    The Wait node's ``resume: webhook`` restart hook answers **GET** by
    default (n8n's ``$parameter["httpMethod"] || "GET"``), so this issues a
    GET, not a POST — a resume ping carries no body anyway.

    Unlike ``rx_prefect.pause_until_healthy`` there is no
    ``ThreadPoolScheduler(1)`` hop: the request is scheduled as a coroutine
    on the rx loop itself (a real asyncio loop), so it neither blocks the
    ``on_next`` callback nor needs a context-free worker thread.
    """
    def _fire(_health) -> None:
        asyncio.run_coroutine_threadsafe(_ping(resume_url), rx_loop.loop)
        if on_resumed is not None:
            on_resumed()

    return rx_loop.subscribe(
        health.pipe(ops.filter(is_healthy), ops.take(1)),
        on_next=_fire,
    )


async def _ping(url: str, attempts: int = 3) -> None:
    """GET *url* with a couple of retries — the Wait node may take a beat to
    register its restart webhook after ``/wait-healthy`` returns 202."""
    for i in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
            if r.status_code < 400:
                return
            print(f"[rx_n8n] resume GET {url} -> {r.status_code} (try {i + 1}/{attempts})")
        except Exception as exc:  # noqa: BLE001 — best-effort; UI can resume by hand
            print(f"[rx_n8n] resume GET {url} failed: {exc} (try {i + 1}/{attempts})")
        await asyncio.sleep(1.5)


def sse_lines(items: Iterable[dict]):
    """Tiny helper for tests / non-async callers: format dicts as SSE frames."""
    for it in items:
        yield f"data: {json.dumps(it)}\n\n"

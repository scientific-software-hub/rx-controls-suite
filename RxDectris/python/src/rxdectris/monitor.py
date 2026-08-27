"""The Monitor subsystem — SIMPLON's own backpressure split, over plain HTTP.

``/images/next`` pops the oldest buffered frame (every frame, in order — the
HTTP analogue of a raw firehose). ``/images/monitor`` returns only the
newest, non-destructively, and the API documentation itself says not to use
anything else above 10 Hz. That is ``share()`` + ``sample()`` already built
into the product — a concrete example to point at when the "why not just use
the REST API" objection comes up.
"""

from __future__ import annotations

import asyncio
from typing import Any

import reactivex as rx

from rxdectris.context import API_VERSION, DetectorContext
from rxdectris.errors import raise_for_simplon_status
from rxdectris.models import Frame

#: SIMPLON returns 408 when no image is available within the requested
#: ?timeout=<ms>; a 404 means the monitor buffer has nothing at all yet.
_EMPTY_STATUS_CODES = (404, 408)


def _decode_monitor_frame(payload: dict[str, Any]) -> Frame:
    return Frame(
        series_id=payload["series_id"],
        series_unique_id=payload["series_unique_id"],
        image_id=payload["image_id"],
        real_time=payload.get("real_time", 0.0),
        start_time=payload.get("start_time", 0.0),
        stop_time=payload.get("stop_time", 0.0),
        counts=payload.get("counts", 0.0),
        data=payload.get("data", b""),
        user_data=payload.get("user_data") or {},
    )


def monitor_images(
    ctx: DetectorContext, poll_ms: int = 500, mode: str = "next", timeout_ms: int = 200
) -> rx.Observable:
    """Poll the Monitor subsystem and emit one :class:`Frame` per poll that finds one.

    *mode* selects the SIMPLON endpoint: ``"next"`` (default, destructive
    FIFO pop — every frame) or ``"monitor"`` (non-destructive, latest only —
    what the documentation recommends for anything faster than 10 Hz). Never
    completes on its own; disposal stops the polling loop.

    .. note::

       The real SIMPLON Monitor subsystem returns ``.tif`` images with
       DECTRIS-private TIFF tags. ``simplon_sim`` returns JSON frame metadata
       instead — a deliberate simplification for this demo, documented in
       ``RxDectris/python/README.md``'s "what is simulated" table.
    """
    if mode not in ("next", "monitor"):
        raise ValueError(f"mode must be 'next' or 'monitor', got {mode!r}")

    def subscribe(observer, scheduler=None):
        async def _poll_loop():
            try:
                while True:
                    try:
                        resp = await ctx.http.get(
                            f"/monitor/api/{API_VERSION}/images/{mode}",
                            params={"timeout": timeout_ms},
                        )
                        if resp.status_code in _EMPTY_STATUS_CODES:
                            await asyncio.sleep(poll_ms / 1000)
                            continue
                        raise_for_simplon_status(resp)
                        observer.on_next(_decode_monitor_frame(resp.json()))
                    except asyncio.CancelledError:
                        return
                    await asyncio.sleep(poll_ms / 1000)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                observer.on_error(exc)

        task = asyncio.ensure_future(_poll_loop())

        def dispose():
            task.cancel()

        return dispose

    return rx.create(subscribe)

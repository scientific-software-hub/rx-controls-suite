"""Stream V2 — the ZeroMQ/CBOR frame push, per SIMPLON 1.8 API documentation §5.4.2.

Real DCU: PUSH socket, CBOR-encoded messages, TCP port 31001, one message per
ZeroMQ frame (not multipart). This module is the client (PULL) side.
"""

from __future__ import annotations

import asyncio
from typing import Any

import cbor2
import reactivex as rx
import zmq

from rxdectris.context import API_VERSION, STREAM_PORT, DetectorContext
from rxdectris.errors import raise_for_simplon_status
from rxdectris.models import Frame, SeriesEnd, SeriesStart


def configure_stream(ctx: DetectorContext, mode: str = "enabled", format: str = "cbor") -> rx.Observable:
    """Enable the Stream V2 data interface: ``PUT stream/api/1.8.0/config/{format,mode}``.

    Without this, ``arm`` succeeds but no data interface is active and the
    Stream V2 socket never emits anything (SIMPLON 1.8 API documentation
    §3.1, "Configure the data interfaces"). Emits once, after both writes
    complete, with the pair of SIMPLON's "changed parameters" responses.
    """

    def subscribe(observer, scheduler=None):
        async def _run():
            try:
                r1 = await ctx.http.put(f"/stream/api/{API_VERSION}/config/format", json={"value": format})
                raise_for_simplon_status(r1)
                r2 = await ctx.http.put(f"/stream/api/{API_VERSION}/config/mode", json={"value": mode})
                raise_for_simplon_status(r2)
                observer.on_next((r1.json(), r2.json()))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_run())

    return rx.create(subscribe)


def _decode(msg: dict[str, Any]) -> SeriesStart | Frame | SeriesEnd:
    kind = msg.get("type")
    if kind == "start":
        return SeriesStart(
            series_id=msg["series_id"],
            series_unique_id=msg["series_unique_id"],
            count_time=msg["count_time"],
            frame_time=msg["frame_time"],
            number_of_images=msg["number_of_images"],
            image_size_x=msg["image_size_x"],
            image_size_y=msg["image_size_y"],
            detector_description=msg.get("detector_description", "RxDectris simulated EIGER2"),
        )
    if kind == "image":
        return Frame(
            series_id=msg["series_id"],
            series_unique_id=msg["series_unique_id"],
            image_id=msg["image_id"],
            real_time=msg["real_time"],
            start_time=msg["start_time"],
            stop_time=msg["stop_time"],
            counts=msg.get("counts", 0.0),
            data=msg.get("data", b""),
            user_data=msg.get("user_data") or {},
        )
    if kind == "end":
        return SeriesEnd(series_id=msg["series_id"], series_unique_id=msg["series_unique_id"])
    raise ValueError(f"unrecognized Stream V2 message type: {kind!r}")


def stream2(ctx: DetectorContext, stream_port: int = STREAM_PORT) -> rx.Observable:
    """Push Observable over the Stream V2 socket — emits :class:`SeriesStart`,
    one :class:`Frame` per exposure, and :class:`SeriesEnd`, in wire order.

    Like :func:`rxtango.monitor_attribute`, this never completes on its own —
    the DCU may arm/trigger/disarm many series over the socket's lifetime.
    Callers that want exactly one series should bound the stream themselves,
    e.g. ``ops.take_while(lambda m: not isinstance(m, SeriesEnd), inclusive=True)``
    — which is exactly what :func:`rxdectris.recipes.acquire_series` does.
    """

    def subscribe(observer, scheduler=None):
        stop = asyncio.Event()

        async def _run():
            try:
                sock = await ctx.stream_socket(stream_port)
            except Exception as exc:
                observer.on_error(exc)
                return
            try:
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(sock.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    except zmq.ZMQError:
                        if stop.is_set():
                            return
                        raise
                    msg = cbor2.loads(raw)
                    observer.on_next(_decode(msg))
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                observer.on_error(exc)

        task = asyncio.ensure_future(_run())

        def dispose():
            stop.set()
            task.cancel()

        return dispose

    return rx.create(subscribe)

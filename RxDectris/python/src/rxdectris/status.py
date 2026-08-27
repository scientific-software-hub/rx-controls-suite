"""Detector status parameters — ``GET .../status/<parameter>`` — and a push wrapper."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import reactivex as rx
import reactivex.operators as ops

from rxdectris.context import API_VERSION, DetectorContext
from rxdectris.errors import raise_for_simplon_status
from rxdectris.models import DetectorState


def read_status(parameter: str, ctx: DetectorContext) -> rx.Observable:
    """Read status *parameter* from the detector module and emit ``resp.json()["value"]``.

    Status parameters are read-only measured values (SIMPLON 1.8 API
    documentation §5.1.2) — this is the single-shot primitive; see
    :func:`monitor_state` for a push wrapper over ``status/state``.
    """

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                resp = await ctx.http.get(f"/detector/api/{API_VERSION}/status/{parameter}")
                raise_for_simplon_status(resp)
                observer.on_next(resp.json()["value"])
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)


def monitor_state(ctx: DetectorContext, poll_ms: int = 500, scheduler=None) -> rx.Observable:
    """Poll ``status/state`` and emit a :class:`DetectorState` on every change.

    SIMPLON has no push notification for detector state, so this is built
    from the same ``interval -> flat_map(read) -> distinct_until_changed``
    idiom as ``demo/synchrotron-beamline/facility.py::ring_health`` — it just
    polls one parameter instead of zipping several. Never completes; the
    subscription's disposal stops the polling.
    """
    return rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_status("state", ctx)),
        ops.map(DetectorState),
        ops.distinct_until_changed(),
    )

"""Detector commands — ``PUT .../command/<name>`` — and the six lifecycle verbs.

Command parameters are write-only (SIMPLON 1.8 API documentation §5.1.3).
``arm``/``disarm``/``abort``/``cancel`` return a ``sequence_id``;
``initialize``/``trigger`` return no body — only the HTTP status matters.
``abort`` drops the pipeline immediately; ``cancel`` stops only after the
image in flight finishes. Both are exposed because the demo's fault
scenarios use ``abort`` (interlock, detector error) while a well-behaved
``disarm`` follows every clean series.
"""

from __future__ import annotations

import asyncio
from typing import Any

import reactivex as rx

from rxdectris.context import API_VERSION, DetectorContext
from rxdectris.errors import raise_for_simplon_status


def send_command(name: str, ctx: DetectorContext, argin: Any = None) -> rx.Observable:
    """Issue detector command *name*, emit its ``sequence_id`` (or ``None``), and complete.

    *argin* is only meaningful for ``trigger`` in ``inte`` (internal-enable)
    mode, where the SIMPLON API accepts a ``count_time`` override in the PUT
    body; every other command takes an empty ``{}`` body.
    """

    def subscribe(observer, scheduler=None):
        async def _run():
            try:
                body = {} if argin is None else {"value": argin}
                resp = await ctx.http.put(f"/detector/api/{API_VERSION}/command/{name}", json=body)
                raise_for_simplon_status(resp)
                data = resp.json() if resp.content else {}
                observer.on_next(data.get("sequence_id"))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_run())

    return rx.create(subscribe)


def initialize(ctx: DetectorContext) -> rx.Observable:
    """``command/initialize`` — mandatory once after DCU boot / DAQ restart."""
    return send_command("initialize", ctx)


def arm(ctx: DetectorContext) -> rx.Observable:
    """``command/arm`` — uploads config to the detector, emits Stream V2 ``start``."""
    return send_command("arm", ctx)


def trigger(ctx: DetectorContext, count_time: float | None = None) -> rx.Observable:
    """``command/trigger`` — starts acquisition. Omit for external trigger modes."""
    return send_command("trigger", ctx, argin=count_time)


def disarm(ctx: DetectorContext) -> rx.Observable:
    """``command/disarm`` — finalizes the series, emits Stream V2 ``end``."""
    return send_command("disarm", ctx)


def abort(ctx: DetectorContext) -> rx.Observable:
    """``command/abort`` — aborts immediately, drops in-flight pipeline data."""
    return send_command("abort", ctx)


def cancel(ctx: DetectorContext) -> rx.Observable:
    """``command/cancel`` — stops after the current image finishes."""
    return send_command("cancel", ctx)

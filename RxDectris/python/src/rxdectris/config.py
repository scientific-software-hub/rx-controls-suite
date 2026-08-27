"""Detector configuration parameters — ``GET``/``PUT .../config/<parameter>``."""

from __future__ import annotations

import asyncio
from typing import Any

import reactivex as rx

from rxdectris.context import API_VERSION, DetectorContext
from rxdectris.errors import raise_for_simplon_status


def read_config(parameter: str, ctx: DetectorContext) -> rx.Observable:
    """Read config *parameter* from the detector module.

    Emits the raw JSON dict SIMPLON returns for a config GET — e.g.
    ``{"min": 0.018, "max": 3600, "value": 0.5, "value_type": "float",
    "access_mode": "rw", "unit": "s"}`` — then completes.
    """

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                resp = await ctx.http.get(f"/detector/api/{API_VERSION}/config/{parameter}")
                raise_for_simplon_status(resp)
                observer.on_next(resp.json())
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)


def write_config(parameter: str, value: Any, ctx: DetectorContext) -> rx.Observable:
    """Write *value* to config *parameter* on the detector module.

    The SIMPLON API keeps the configuration internally consistent — a write
    can cascade into other parameters (e.g. ``count_time`` forcing
    ``frame_time`` up). Emits the list of parameter names SIMPLON reports as
    changed, exactly as the real ``PUT`` response does.
    """

    def subscribe(observer, scheduler=None):
        async def _write():
            try:
                resp = await ctx.http.put(
                    f"/detector/api/{API_VERSION}/config/{parameter}", json={"value": value}
                )
                raise_for_simplon_status(resp)
                observer.on_next(resp.json())
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_write())

    return rx.create(subscribe)

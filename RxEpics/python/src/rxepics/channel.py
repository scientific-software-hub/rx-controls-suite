"""Single-shot PV read as an Observable."""

import asyncio

import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context

from rxepics.reading import Reading


def read_pv_ts(pv_name: str, ctx: Context) -> rx.Observable:
    """Return an Observable that emits one :class:`Reading` from *pv_name*
    and completes.

    Requests a time-bearing DBR (``data_type='time'``) so ``reading.ts``
    carries the CA server's own timestamp of when the value last changed —
    not the wall-clock moment this read happened to complete, which may be
    considerably later on a slow-changing PV. Verified against caproto
    1.3.0's asyncio client: ``PV.read(data_type='time')`` returns a
    response whose ``.metadata`` is a ``DBR_TIME_*`` struct with
    ``.timestamp`` (float POSIX seconds) and ``.severity``
    (``AlarmSeverity``).
    """

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                reading = await pv.read(data_type="time")
                observer.on_next(Reading(
                    value=float(reading.data[0]),
                    ts=reading.metadata.timestamp,
                    quality=reading.metadata.severity,
                ))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)


def read_pv(pv_name: str, ctx: Context) -> rx.Observable:
    """Return an Observable that emits one float value from *pv_name* and completes.

    A thin projection of :func:`read_pv_ts` — the source-timestamp/quality
    are discarded here, not re-fetched; this is the same one CA read
    either way.
    """
    return read_pv_ts(pv_name, ctx).pipe(ops.map(lambda r: r.value))

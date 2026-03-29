"""Single-shot PV read as an Observable."""

import asyncio

import reactivex as rx
from caproto.asyncio.client import Context


def read_pv(pv_name: str, ctx: Context) -> rx.Observable:
    """Return an Observable that emits one float value from *pv_name* and completes."""

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                reading = await pv.read()
                observer.on_next(float(reading.data[0]))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)

"""Single-shot PV write as an Observable."""

import asyncio

import reactivex as rx
from caproto.asyncio.client import Context


def write_pv(pv_name: str, value, ctx: Context) -> rx.Observable:
    """Write *value* to *pv_name* and return an Observable that emits the written value."""

    def subscribe(observer, scheduler=None):
        async def _write():
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                await pv.write([value])
                observer.on_next(value)
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_write())

    return rx.create(subscribe)

"""CA monitor as a push Observable."""

import asyncio

import reactivex as rx
from caproto.asyncio.client import Context


def monitor_pv(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable that emits a float on every CA monitor update.

    The CA subscription is created lazily on the first subscriber.
    Disposing the subscription clears the CA monitor.
    """

    def subscribe(observer, scheduler=None):
        ca_sub = None

        def callback(response):
            try:
                observer.on_next(float(response.data[0]))
            except Exception:
                pass

        async def _start():
            nonlocal ca_sub
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                ca_sub = pv.subscribe()
                ca_sub.add_callback(callback)
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            if ca_sub is not None:
                ca_sub.clear()

        return dispose

    return rx.create(subscribe)

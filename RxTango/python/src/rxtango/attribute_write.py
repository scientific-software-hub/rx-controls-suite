"""Single-shot Tango attribute write as an Observable."""

import asyncio

import reactivex as rx

from rxtango.context import TangoContext


def write_attribute(device: str, name: str, value) -> rx.Observable:
    """Write *value* to attribute *name* on *device* and emit the written value.

    Re-emitting the written value (rather than ``None``) allows writes to be
    chained into subsequent steps — the same design as
    :func:`rxepics.channel_write.write_pv`.

    This mirrors ``RxTangoAttributeWrite<T>`` in the Java library.
    """

    def subscribe(observer, scheduler=None):
        async def _write():
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, TangoContext.get_proxy, device)
                await loop.run_in_executor(None, proxy.write_attribute, name, value)
                observer.on_next(value)
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_write())

    return rx.create(subscribe)

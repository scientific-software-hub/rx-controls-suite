"""Single-shot Tango attribute read as an Observable."""

import asyncio

import reactivex as rx

from rxtango.context import TangoContext


def read_attribute(device: str, name: str) -> rx.Observable:
    """Return an Observable that reads *name* from *device* and emits one value.

    The attribute value (``DeviceAttribute.value``) is emitted and the
    Observable completes immediately.  On any Tango error the error propagates
    via ``on_error``.

    This is the Python equivalent of ``RxTangoAttribute<T>`` in the Java
    library and mirrors :func:`rxepics.channel.read_pv`.
    """

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, TangoContext.get_proxy, device)
                da = await loop.run_in_executor(None, proxy.read_attribute, name)
                observer.on_next(da.value)
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)

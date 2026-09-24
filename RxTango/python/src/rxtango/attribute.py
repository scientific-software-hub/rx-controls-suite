"""Single-shot Tango attribute read as an Observable."""

import asyncio

import reactivex as rx
import reactivex.operators as ops

from rxtango.context import TangoContext
from rxtango.reading import Reading


def read_attribute_ts(device: str, name: str) -> rx.Observable:
    """Return an Observable that reads *name* from *device* and emits one
    :class:`Reading`, then completes.

    ``reading.ts`` is ``DeviceAttribute.time.totime()`` — the Tango device
    server's own timestamp of when the attribute last changed, which on a
    slow-changing attribute can be considerably older than the moment this
    read actually completed. ``reading.quality`` is
    ``DeviceAttribute.quality`` (a ``tango.AttrQuality``). Verified against
    pytango 10.3.1: ``DeviceAttribute`` exposes both ``time`` and
    ``quality`` unconditionally, no extra request flag needed (unlike
    caproto's ``data_type='time'``).

    On any Tango error the error propagates via ``on_error``.
    """

    def subscribe(observer, scheduler=None):
        async def _read():
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, TangoContext.get_proxy, device)
                da = await loop.run_in_executor(None, proxy.read_attribute, name)
                observer.on_next(Reading(
                    value=da.value,
                    ts=da.time.totime(),
                    quality=da.quality,
                ))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_read())

    return rx.create(subscribe)


def read_attribute(device: str, name: str) -> rx.Observable:
    """Return an Observable that reads *name* from *device* and emits one value.

    The attribute value (``DeviceAttribute.value``) is emitted and the
    Observable completes immediately.  On any Tango error the error propagates
    via ``on_error``.

    This is the Python equivalent of ``RxTangoAttribute<T>`` in the Java
    library and mirrors :func:`rxepics.channel.read_pv`.

    A thin projection of :func:`read_attribute_ts` — the source-timestamp/
    quality are discarded here, not re-fetched; this is the same one Tango
    read either way.
    """
    return read_attribute_ts(device, name).pipe(ops.map(lambda r: r.value))

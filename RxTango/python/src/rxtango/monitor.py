"""Tango event subscription as a push Observable."""

import asyncio

import tango
import reactivex as rx

from rxtango.context import TangoContext

_EVENT_TYPE_MAP: dict[str, tango.EventType] = {
    "change":   tango.EventType.CHANGE_EVENT,
    "periodic": tango.EventType.PERIODIC_EVENT,
    "archive":  tango.EventType.ARCHIVE_EVENT,
}


def monitor_attribute(device: str, name: str, event: str = "change") -> rx.Observable:
    """Return a push Observable that emits the attribute value on every Tango event.

    *event* selects the event type: ``"change"`` (default), ``"periodic"``, or
    ``"archive"``.  The Observable never completes — it runs until the returned
    disposable is disposed, at which point ``proxy.unsubscribe_event`` is called.

    Tango event callbacks arrive on a C++ thread; values are safely dispatched
    back to the asyncio event loop via ``loop.call_soon_threadsafe``.

    This mirrors :func:`rxepics.monitor.monitor_pv` and
    ``RxTangoAttributeChangePublisher<T>`` in the Java library.

    .. note::

        Tango events require a properly configured Tango event system (zmq ports
        reachable from the client, event heartbeat).  The subscription is created
        lazily on the first subscriber.
    """
    event_type = _EVENT_TYPE_MAP.get(event.lower(), tango.EventType.CHANGE_EVENT)

    def subscribe(observer, scheduler=None):
        event_id: int | None = None
        proxy_holder: list = [None]  # mutable cell shared with dispose()

        async def _start():
            nonlocal event_id
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, TangoContext.get_proxy, device)
                proxy_holder[0] = proxy

                def callback(event_data):
                    try:
                        value = event_data.attr_value.value
                        loop.call_soon_threadsafe(observer.on_next, value)
                    except Exception:
                        pass

                # subscribe_event is synchronous; run in executor to avoid blocking
                event_id = await loop.run_in_executor(
                    None, proxy.subscribe_event, name, event_type, callback
                )
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            if event_id is not None and proxy_holder[0] is not None:
                try:
                    proxy_holder[0].unsubscribe_event(event_id)
                except Exception:
                    pass

        return dispose

    return rx.create(subscribe)

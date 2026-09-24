"""Shared plumbing for the EPICS CA push sources (``monitor.py``, ``connection.py``).

Both call sites need the same shape: locate the PV lazily, register a
two-argument callback on some caproto *registration object* (a
``Subscription`` for ``monitor_pv``/``monitor_errors``, or the PV's
``connection_state_callback`` — a plain ``CallbackHandler`` — for
``connection_status``), keep that callback alive independent of the Rx
observer graph, and unregister on dispose.

caproto's asyncio client stores subscription and connection-state callbacks
by *weakref* (``CallbackHandler.add_callback``). A closure kept alive only
via the chain ``subscribe() -> dispose -> AutoDetachObserver`` is not
enough: that chain is a reference *cycle* back through the closure's own
captured ``observer``, and every example in this library discards the
Disposable ``.subscribe()`` returns (they run until Ctrl+C) — so once
nothing external holds that cycle, a ``gc.collect()`` pass reaps it and the
weakref-backed callback dies with it, silently dropping the subscription.
``_KEEPALIVE`` pins the callback by identity until ``dispose()`` explicitly
unpins it, independent of what the Rx observer graph does.

This module only extracts the duplicated plumbing that used to live
separately in ``monitor.py`` and ``connection.py`` — no behavior change.
"""

import asyncio

import reactivex as rx
from caproto import CaprotoError
from caproto.asyncio.client import Context

_KEEPALIVE: set = set()


def ca_push_source(
    pv_name: str,
    ctx: Context,
    *,
    get_registration,
    make_callback,
    add_callback,
    teardown,
    initial=None,
) -> rx.Observable:
    """Build a push Observable backed by one caproto registration object.

    *get_registration(pv)* returns the object callbacks are added to (a
    ``Subscription``, or ``pv.connection_state_callback``).
    *make_callback(observer)* returns the actual callback closure — a
    plain ``func(x, y)`` matching caproto's own two-argument shape (e.g.
    ``func(sub, response)`` or ``func(pv, state)``); see
    :func:`simple_callback` for the common case.
    *add_callback(registration, callback)* registers *callback* and
    returns the token ``remove_callback``/``clear`` would need.
    *teardown(registration, token)* unregisters on dispose.
    *initial(observer)*, if given, runs synchronously before the PV is
    even located (``connection_status``'s synthetic ``on_next(False)``,
    so the observable stays total instead of silent until first connect).
    """

    def subscribe(observer, scheduler=None):
        if initial is not None:
            initial(observer)

        registration = None
        token = None
        callback = None
        disposed = False

        async def _start():
            nonlocal registration, token, callback
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                if disposed:
                    return
                registration = get_registration(pv)
                callback = make_callback(observer)
                token = add_callback(registration, callback)
                _KEEPALIVE.add(callback)
            except CaprotoError as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            nonlocal disposed
            disposed = True
            _KEEPALIVE.discard(callback)
            if registration is not None:
                teardown(registration, token)

        return dispose

    return rx.create(subscribe)


def simple_callback(handler):
    """``make_callback`` for the common case: ``handler(observer, value)``.

    Returns a factory ``observer -> callback(x, y)`` where *callback*
    forwards its second positional argument to *handler* alongside
    *observer* — matching both caproto callback shapes
    (``func(sub, response)`` and ``func(pv, state)``); the first argument
    (the registration object / PV) is discarded, matching what both
    existing call sites already do.
    """

    def factory(observer):
        def callback(_registration, value):
            handler(observer, value)

        return callback

    return factory

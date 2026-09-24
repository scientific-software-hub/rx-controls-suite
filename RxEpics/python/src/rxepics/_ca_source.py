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

The callback is pinned *on the registration object itself* — a caproto
``Subscription`` or ``CallbackHandler`` is a plain object with no
``__slots__``, so an attribute is attachable — keyed by the token
``add_callback`` returns, rather than in a process-global set. The
registration object is itself rooted for as long as its PV is: caproto
caches one ``Subscription`` per ``(PV, params)`` in ``PV.subscriptions``
and never evicts it even after its last callback is removed, and
``connection_state_callback`` is a fixed attribute created once in
``PV.__init__``. So repeated create/dispose cycles against the *same* PV
reuse the *same* registration object and the *same* pin dict — add on
subscribe, discard on dispose, never growing across cycles. Disposal is
no longer required for correctness (an un-disposed subscription's
callback stays reachable through the registration object it belongs to,
not through the Rx graph), and the pinning can never grow unboundedly the
way the earlier process-global set did.
"""

import asyncio

import reactivex as rx
from caproto import CaprotoError
from caproto.asyncio.client import Context


def _pins(registration) -> dict:
    """Return (creating if absent) the pin dict attached to *registration*."""
    try:
        return registration._rx_pins
    except AttributeError:
        registration._rx_pins = {}
        return registration._rx_pins


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
    returns a token.
    *teardown(registration, token)* unregisters exactly that one callback
    — never every callback on the registration, so a sibling observable
    sharing it (e.g. ``monitor_pv`` and ``monitor_errors`` on the same PV,
    sharing one ``Subscription``) is unaffected.
    *initial(observer)*, if given, runs synchronously before the PV is
    even located (``connection_status``'s synthetic ``on_next(False)``,
    so the observable stays total instead of silent until first connect).
    """

    def subscribe(observer, scheduler=None):
        if initial is not None:
            initial(observer)

        registration = None
        token = None
        disposed = False

        async def _start():
            nonlocal registration, token
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                if disposed:
                    return
                registration = get_registration(pv)
                callback = make_callback(observer)
                token = add_callback(registration, callback)
                if disposed:
                    # dispose() raced in between the guard above and
                    # add_callback actually registering — unregister
                    # immediately rather than leak a live callback that
                    # nothing will ever call dispose() on again.
                    teardown(registration, token)
                    registration = None
                    token = None
                    return
                _pins(registration)[token] = callback
            except CaprotoError as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            nonlocal disposed
            disposed = True
            if registration is not None and token is not None:
                _pins(registration).pop(token, None)
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

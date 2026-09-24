"""CA connection state as a push Observable."""

import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context

from rxepics._ca_source import ca_push_source, simple_callback


def connection_status(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable of ``bool`` — ``True`` while *pv_name* is
    connected over Channel Access.

    Emits the current state immediately on subscribe (``False`` if the PV
    has never connected — caproto does not fire its connection callback
    until a channel is created, so this observable synthesizes that initial
    state to stay total), then one value per transition. Never completes.

    Composes directly as a Bluesky suspender signal or a status LED:

    >>> connection_status("TEST:CALC", ctx).subscribe(on_next=set_link_led)
    """

    def handler(observer, state):
        observer.on_next(state == "connected")

    source = ca_push_source(
        pv_name,
        ctx,
        get_registration=lambda pv: pv.connection_state_callback,
        make_callback=simple_callback(handler),
        # run=True replays the current state if the PV already connected
        # between the synthetic on_next(False) below and here; a PV that
        # has never connected replays nothing, which is why the synthetic
        # False exists in the first place.
        add_callback=lambda registration, callback: registration.add_callback(callback, run=True),
        teardown=lambda registration, token: registration.remove_callback(token),
        initial=lambda observer: observer.on_next(False),
    )
    return source.pipe(ops.distinct_until_changed())

"""CA connection state as a push Observable."""

import asyncio

import reactivex as rx
import reactivex.operators as ops
from caproto import CaprotoError
from caproto.asyncio.client import Context

# See the identical note in monitor.py: the callback must be pinned by
# identity, not merely reachable through the Rx observer/disposable graph,
# because that graph is a reference cycle a gc pass can reap once the
# caller discards subscribe()'s return value (as every example in this
# library does).
_KEEPALIVE: set = set()


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

    def subscribe(observer, scheduler=None):
        observer.on_next(False)

        pv_ref = None
        token = None
        disposed = False

        def callback(pv, state):
            observer.on_next(state == "connected")

        async def _start():
            nonlocal pv_ref, token
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                if disposed:
                    return
                pv_ref = pv
                # run=True replays the current state if the PV already
                # connected between the synthetic on_next(False) above and
                # here; a PV that has never connected replays nothing, which
                # is why the synthetic False exists in the first place.
                token = pv.connection_state_callback.add_callback(callback, run=True)
                _KEEPALIVE.add(callback)
            except CaprotoError as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            nonlocal disposed
            disposed = True
            _KEEPALIVE.discard(callback)
            if pv_ref is not None and token is not None:
                pv_ref.connection_state_callback.remove_callback(token)

        return dispose

    return rx.create(subscribe).pipe(ops.distinct_until_changed())

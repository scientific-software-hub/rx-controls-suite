"""CA monitor as a push Observable."""

import asyncio
import logging

import reactivex as rx
from caproto import CaprotoError
from caproto.asyncio.client import Context

from rxepics.errors import PvUpdateError

log = logging.getLogger(__name__)


def _monitor_updates(pv_name: str, ctx: Context, handler) -> rx.Observable:
    """Shared CA-subscription plumbing for the update-driven observables.

    *handler(observer, response)* is invoked for every CA update; it decides
    how a given response becomes (or does not become) a message on the
    stream. Only setup failures (PV cannot be located, subscription cannot
    be created) reach ``on_error`` here — per-update handling is entirely
    *handler*'s call, so it never terminates the stream on its own.

    caproto caches ``Subscription`` objects per (PV, params), so
    :func:`monitor_pv` and :func:`monitor_errors` on the same PV share one
    underlying CA subscription.
    """

    def subscribe(observer, scheduler=None):
        ca_sub = None

        # caproto's asyncio client calls subscription callbacks as
        # func(sub, response) and stores them by weakref (CallbackHandler);
        # a bare closure with no other referent would be garbage-collected
        # and silently deregistered, so it must be kept alive explicitly.
        def callback(sub, response):
            handler(observer, response)

        async def _start():
            nonlocal ca_sub
            try:
                (pv,) = await ctx.get_pvs(pv_name)
                ca_sub = pv.subscribe()
                ca_sub.add_callback(callback)
            except CaprotoError as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_start())

        def dispose():
            callback  # keep the strong reference alive until disposal (see note above)
            if ca_sub is not None:
                asyncio.ensure_future(ca_sub.clear())

        return dispose

    return rx.create(subscribe)


def monitor_pv(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable that emits a float on every CA monitor update.

    The CA subscription is created lazily on the first subscriber.
    Disposing the subscription clears the CA monitor.

    A value that fails to convert, or arrives with a non-normal CA status, is
    logged at WARNING on ``rxepics.monitor`` and skipped — it does not
    terminate the stream. Use :func:`rxepics.errors.monitor_errors` to observe
    these failures as messages instead of log lines. Only a *setup* failure
    (the PV cannot be located, or a subscription cannot be created) is
    terminal and reaches ``on_error``.
    """

    def handler(observer, response):
        try:
            if response.status.success:
                observer.on_next(float(response.data[0]))
            else:
                log.warning(
                    "%s: non-normal CA status on update: %s",
                    pv_name, response.status,
                )
        except Exception:
            log.warning(
                "%s: failed to convert monitor update %r", pv_name, response,
                exc_info=True,
            )

    return _monitor_updates(pv_name, ctx, handler)


def monitor_errors(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable of :class:`PvUpdateError`, one per bad update.

    Shares its underlying CA subscription with :func:`monitor_pv` on the same
    PV (caproto deduplicates by subscription parameters). Never completes and
    never calls ``on_error`` for a per-update failure — only a setup failure
    is terminal, matching :func:`monitor_pv`.
    """

    def handler(observer, response):
        if not response.status.success:
            observer.on_next(PvUpdateError(pv_name, response))
            return
        try:
            float(response.data[0])
        except Exception as exc:
            observer.on_next(PvUpdateError(pv_name, response, cause=exc))

    return _monitor_updates(pv_name, ctx, handler)

"""CA monitor as a push Observable."""

import asyncio
import logging

import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context

from rxepics._ca_source import ca_push_source, simple_callback
from rxepics.errors import PvUpdateError
from rxepics.reading import Reading

log = logging.getLogger(__name__)


def _monitor_updates(pv_name: str, ctx: Context, handler) -> rx.Observable:
    """Shared CA-subscription plumbing for the update-driven observables.

    *handler(observer, response)* is invoked for every CA update; it decides
    how a given response becomes (or does not become) a message on the
    stream. Only setup failures (PV cannot be located, subscription cannot
    be created) reach ``on_error`` here — per-update handling is entirely
    *handler*'s call, so it never terminates the stream on its own.

    Requests a time-bearing DBR (``data_type='time'``) so every handler's
    ``response.metadata`` carries the CA server's own timestamp/severity —
    needed by :func:`monitor_pv_ts`. caproto's ``Subscription`` cache is
    keyed on the full bound-argument signature including ``data_type``, so
    :func:`monitor_pv`, :func:`monitor_pv_ts`, and :func:`monitor_errors`
    on the same PV all request ``'time'`` and therefore still share one
    underlying CA subscription.
    """
    return ca_push_source(
        pv_name,
        ctx,
        get_registration=lambda pv: pv.subscribe(data_type="time"),
        make_callback=simple_callback(handler),
        add_callback=lambda registration, callback: registration.add_callback(callback),
        # remove_callback(token), not clear(): clear() tears down every
        # callback on the Subscription, including a co-subscribed
        # monitor_errors on the same PV (they share one CA subscription —
        # see the docstring above). remove_callback is a coroutine on the
        # asyncio client, same as clear() was, and caproto auto-unsubscribes
        # once the last callback is removed.
        teardown=lambda registration, token: asyncio.ensure_future(
            registration.remove_callback(token)
        ),
    )


def monitor_pv_ts(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable that emits a :class:`Reading` on every CA
    monitor update.

    Same resilience contract as :func:`monitor_pv`: a value that fails to
    convert, or arrives with a non-normal CA status, is logged at WARNING
    and skipped, never terminal; only a setup failure reaches ``on_error``.
    """

    def handler(observer, response):
        try:
            if response.status.success:
                observer.on_next(Reading(
                    value=float(response.data[0]),
                    ts=response.metadata.timestamp,
                    quality=response.metadata.severity,
                ))
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


def monitor_pv(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable that emits a float on every CA monitor update.

    The CA subscription is created lazily on the first subscriber.
    Disposing the subscription clears the CA monitor.

    A value that fails to convert, or arrives with a non-normal CA status, is
    logged at WARNING on ``rxepics.monitor`` and skipped — it does not
    terminate the stream. Use :func:`rxepics.monitor.monitor_errors` to observe
    these failures as messages instead of log lines. Only a *setup* failure
    (the PV cannot be located, or a subscription cannot be created) is
    terminal and reaches ``on_error``.

    A thin projection of :func:`monitor_pv_ts` — the source-timestamp/
    quality are discarded here, not re-requested; this is the same one CA
    subscription either way.
    """
    return monitor_pv_ts(pv_name, ctx).pipe(ops.map(lambda r: r.value))


def monitor_errors(pv_name: str, ctx: Context) -> rx.Observable:
    """Return a push Observable of :class:`PvUpdateError`, one per bad update.

    Shares its underlying CA subscription with :func:`monitor_pv` /
    :func:`monitor_pv_ts` on the same PV (caproto deduplicates by
    subscription parameters, including ``data_type``). Never completes and
    never calls ``on_error`` for a per-update failure — only a setup
    failure is terminal, matching :func:`monitor_pv`.
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

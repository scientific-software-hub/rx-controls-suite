"""Exponential-backoff retry for the single-shot observables."""

from __future__ import annotations

from datetime import timedelta
from typing import Callable

import reactivex as rx
import reactivex.operators as ops


def retry_with_backoff(
    max_retries: int = 3,
    base_delay_ms: int = 500,
    scheduler=None,
) -> Callable[[rx.Observable], rx.Observable]:
    """Return an operator that retries a failed :func:`read_pv` /
    :func:`write_pv` observable with exponential backoff.

    Only meaningful for the single-shot observables — a re-subscribe here
    means "try the read/write again", not "resume a stream". CA monitors do
    not need this: caproto already re-arms a dropped subscription on its own
    (see the README's Resilience section).

    Retries *max_retries* times, doubling the delay each attempt starting
    from *base_delay_ms*. After the last attempt fails, the original error
    propagates via ``on_error``. Requires a *scheduler* bound to the same
    asyncio loop the source observable was created on, since a retried
    read/write re-enters ``asyncio.ensure_future``.

    >>> read_pv("TEST:CALC", ctx).pipe(
    ...     retry_with_backoff(max_retries=5, scheduler=scheduler)
    ... ).subscribe(on_next=print, on_error=print)
    """

    def attempt(source: rx.Observable, attempt_num: int) -> rx.Observable:
        # Each retry must re-wrap in catch, or only the *first* failure is
        # ever handled — a second failure on the resubscribed source would
        # propagate uncaught straight to on_error regardless of max_retries.
        def catch_fn(exc, _src):
            if attempt_num >= max_retries:
                return rx.throw(exc)
            delay = timedelta(milliseconds=base_delay_ms * (2 ** attempt_num))
            return rx.timer(delay, scheduler=scheduler).pipe(
                ops.flat_map(lambda _: attempt(source, attempt_num + 1))
            )

        return source.pipe(ops.catch(catch_fn))

    return lambda src: rx.defer(lambda _: attempt(src, 0))

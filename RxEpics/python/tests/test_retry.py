"""Tests for retry_with_backoff — composable retry for the single-shot paths."""

import asyncio

import reactivex as rx
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.retry import retry_with_backoff


def _run(coro):
    return asyncio.run(coro)


def _flaky_source(fail_count: int, attempts: list):
    """An Observable that fails `fail_count` times, then succeeds."""
    def subscribe(observer, scheduler=None):
        attempts.append(1)
        if len(attempts) <= fail_count:
            observer.on_error(RuntimeError(f"fail {len(attempts)}"))
        else:
            observer.on_next("ok")
            observer.on_completed()
        return lambda: None
    return rx.create(subscribe)


def test_retries_until_success(fake_ctx):
    attempts = []
    results = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()
        _flaky_source(2, attempts).pipe(
            retry_with_backoff(max_retries=5, base_delay_ms=5, scheduler=scheduler)
        ).subscribe(
            on_next=results.append, on_completed=done.set, scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=5)

    _run(run())
    assert len(attempts) == 3  # 2 failures + 1 success
    assert results == ["ok"]


def test_propagates_error_after_exhausting_retries(fake_ctx):
    """A second failure after the first retry must still be caught — a flat
    ops.catch(handler) only handles the *first* error; the recursive
    operator must re-wrap catch on every attempt."""
    attempts = []
    errors = []

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        done = asyncio.Event()
        _flaky_source(999, attempts).pipe(
            retry_with_backoff(max_retries=2, base_delay_ms=5, scheduler=scheduler)
        ).subscribe(
            on_next=lambda v: None,
            on_error=lambda e: (errors.append(e), done.set()),
            scheduler=scheduler,
        )
        await asyncio.wait_for(done.wait(), timeout=5)

    _run(run())
    assert len(attempts) == 3  # initial + 2 retries
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_independent_pipelines_do_not_share_attempt_state(fake_ctx):
    """The same operator instance applied to two independent sources must
    give each its own retry budget — no shared mutable counter across
    unrelated pipelines (the bug an operator-level `attempt = [0]` list
    would reintroduce)."""

    async def run():
        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        op = retry_with_backoff(max_retries=3, base_delay_ms=5, scheduler=scheduler)

        for _ in range(2):
            attempts = []
            done = asyncio.Event()
            _flaky_source(1, attempts).pipe(op).subscribe(
                on_completed=done.set, scheduler=scheduler,
            )
            await asyncio.wait_for(done.wait(), timeout=5)
            assert len(attempts) == 2, "each pipeline must get its own retry budget"

    _run(run())

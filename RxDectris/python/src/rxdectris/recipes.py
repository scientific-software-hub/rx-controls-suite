"""The detector-lifecycle recipe: configure -> arm -> trigger -> frames -> disarm."""

from __future__ import annotations

import asyncio

import reactivex as rx

from rxdectris.command import abort, arm, disarm, trigger
from rxdectris.config import write_config
from rxdectris.context import DetectorContext
from rxdectris.models import SeriesEnd
from rxdectris.stream import configure_stream, stream2


def _await_obs(observable: rx.Observable):
    """Bridge a single-shot Observable (one value or one error) to an awaitable."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    def on_next(value):
        if not future.done():
            future.set_result(value)

    def on_error(exc):
        if not future.done():
            future.set_exception(exc)

    observable.subscribe(on_next=on_next, on_error=on_error)
    return future


def acquire_series(
    ctx: DetectorContext,
    frames: int,
    count_time: float,
    frame_time: float | None = None,
    trigger_mode: str = "ints",
) -> rx.Observable:
    """Acquire one series of *frames* images at *count_time* seconds each.

    The recipe, in order:

    1. configure — ``nimages``, ``count_time``, ``frame_time`` (if given),
       ``trigger_mode``
    2. enable the Stream V2 interface
    3. subscribe to the Stream V2 socket — **before** ``arm``, because ``arm``
       is what emits the ``start`` message; arming first would race the
       socket connection
    4. ``arm``, then ``trigger`` (only for internal trigger modes — ``ints``,
       ``inte`` — per the SIMPLON documentation; external modes must be
       triggered by the facility instead)
    5. re-emit every Stream V2 message until ``SeriesEnd``
    6. ``disarm``

    Teardown is unconditional and exactly-once: disposal or any error at any
    point issues ``abort`` (immediate, drops the pipeline); the clean path
    issues ``disarm`` once ``SeriesEnd`` has arrived. This is what makes the
    fault scenarios safe to chain in the live demo — the detector always
    lands back in ``idle``, whichever branch fired.
    """

    def subscribe(observer, scheduler=None):
        torn_down = False
        stream_disposable = None

        async def _teardown(clean: bool) -> None:
            nonlocal torn_down
            if torn_down:
                return
            torn_down = True
            try:
                await _await_obs(disarm(ctx) if clean else abort(ctx))
            except Exception:
                pass  # best-effort — the original error/completion still propagates

        async def _run():
            nonlocal stream_disposable
            drain_task: asyncio.Task | None = None
            try:
                await _await_obs(write_config("nimages", frames, ctx))
                await _await_obs(write_config("count_time", count_time, ctx))
                if frame_time is not None:
                    await _await_obs(write_config("frame_time", frame_time, ctx))
                await _await_obs(write_config("trigger_mode", trigger_mode, ctx))
                await _await_obs(configure_stream(ctx))

                queue: asyncio.Queue = asyncio.Queue()
                stream_disposable = stream2(ctx).subscribe(
                    on_next=queue.put_nowait,
                    on_error=queue.put_nowait,
                )

                async def _drain() -> None:
                    # Forwards every Stream V2 message to the observer as it
                    # arrives — started before `arm`/`trigger` so a message
                    # already reaches the caller even if a *later* command
                    # (e.g. an injected fault on `trigger`) then fails.
                    while True:
                        item = await queue.get()
                        if isinstance(item, Exception):
                            raise item
                        observer.on_next(item)
                        if isinstance(item, SeriesEnd):
                            return

                drain_task = asyncio.ensure_future(_drain())

                await _await_obs(arm(ctx))
                if trigger_mode.startswith("int"):
                    await _await_obs(trigger(ctx))

                await drain_task  # waits for SeriesEnd (or re-raises drain_task's exception)

                await _teardown(clean=True)
                observer.on_completed()
            except asyncio.CancelledError:
                if drain_task is not None and not drain_task.done():
                    drain_task.cancel()
                await _teardown(clean=False)
            except Exception as exc:
                if drain_task is not None and not drain_task.done():
                    drain_task.cancel()
                await _teardown(clean=False)
                observer.on_error(exc)
            finally:
                if stream_disposable is not None:
                    stream_disposable.dispose()

        task = asyncio.ensure_future(_run())

        def dispose():
            task.cancel()

        return dispose

    return rx.create(subscribe)

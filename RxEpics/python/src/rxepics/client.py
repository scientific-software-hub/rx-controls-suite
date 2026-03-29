"""Fluent EpicsClient — mirrors TangoClient for EPICS PVs."""

from __future__ import annotations

from typing import Callable

import reactivex.operators as ops
from caproto.asyncio.client import Context

from rxepics.channel import read_pv
from rxepics.channel_write import write_pv
from rxepics.monitor import monitor_pv


class EpicsClient:
    """Fluent builder for sequential EPICS PV operations.

    Each method appends a step to an internal Rx chain. Steps are NOT
    executed until a terminal method (``subscribe``) is called. Results
    flow through the chain: each step receives the result of the previous
    step, so later steps can compute their inputs dynamically.

    EPICS has no commands — use ``write`` to a PV instead.

    Example — read, calibrate, write back::

        async def main():
            ctx = Context()
            loop = asyncio.get_running_loop()
            scheduler = AsyncIOScheduler(loop)
            done = asyncio.Event()

            EpicsClient(ctx) \\
                .read("TEST:CALC") \\
                .map(lambda v: abs(v) * 2.0 + 1.5) \\
                .write("TEST:DOUBLE") \\
                .map(lambda v: f"calibrated={v:.4f}") \\
                .write("TEST:STRING") \\
                .read("TEST:STRING") \\
                .subscribe(
                    on_next=print,
                    on_completed=done.set,
                    scheduler=scheduler,
                )

            await done.wait()
    """

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._chain = None  # rx.Observable, built lazily

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(self, pv_name: str) -> EpicsClient:
        """Read *pv_name*. The float value becomes the input for the next step."""
        if self._chain is None:
            self._chain = read_pv(pv_name, self._ctx)
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: read_pv(pv_name, self._ctx))
            )
        return self

    # ------------------------------------------------------------------
    # monitor
    # ------------------------------------------------------------------

    def monitor(self, pv_name: str) -> EpicsClient:
        """Subscribe to CA monitor updates for *pv_name* (push, multi-value).

        Can only be used as the *first* step; chaining a monitor after
        another step is not supported.
        """
        if self._chain is not None:
            raise RuntimeError("monitor() must be the first step in an EpicsClient chain")
        self._chain = monitor_pv(pv_name, self._ctx)
        return self

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(self, pv_name: str, value=None) -> EpicsClient:
        """Write to *pv_name*.

        *value* can be:
        - omitted / ``None`` — write the result of the previous step
        - a static value — written as-is, ignoring the previous result
        - a callable ``fn(prev) -> value`` — called with the previous result

        The written value becomes the input for the next step.
        """
        if callable(value):
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_pv(pv_name, value(prev), self._ctx))
            )
        elif value is None:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_pv(pv_name, prev, self._ctx))
            )
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: write_pv(pv_name, value, self._ctx))
            )
        return self

    # ------------------------------------------------------------------
    # map
    # ------------------------------------------------------------------

    def map(self, fn: Callable) -> EpicsClient:
        """Apply a pure transformation to the current value without any I/O."""
        self._chain = self._chain.pipe(ops.map(fn))
        return self

    # ------------------------------------------------------------------
    # Terminal operator
    # ------------------------------------------------------------------

    def subscribe(self, on_next=None, on_error=None, on_completed=None, scheduler=None):
        """Subscribe to the chain. Execution starts immediately.

        Returns a disposable that can be used to cancel an in-flight operation.
        """
        if self._chain is None:
            raise RuntimeError("EpicsClient chain is empty — add at least one step before subscribing")
        return self._chain.subscribe(
            on_next=on_next,
            on_error=on_error,
            on_completed=on_completed,
            scheduler=scheduler,
        )

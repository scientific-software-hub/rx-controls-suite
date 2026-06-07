"""Fluent TangoClient — mirrors EpicsClient for Tango devices."""

from __future__ import annotations

from typing import Callable

import reactivex.operators as ops

from rxtango.attribute import read_attribute
from rxtango.attribute_write import write_attribute
from rxtango.command import execute_command
from rxtango.monitor import monitor_attribute


class TangoClient:
    """Fluent builder for sequential Tango operations.

    Each method appends a step to an internal Rx chain.  Steps are NOT
    executed until a terminal method (``subscribe``) is called.  Results
    flow through the chain: each step receives the result of the previous
    step, so later steps can compute their inputs dynamically.

    Unlike the EPICS equivalent, Tango has commands — use ``execute()``
    to issue them alongside ``read()`` and ``write()``.

    Example — read, calibrate, write back::

        async def main():
            loop = asyncio.get_running_loop()
            scheduler = AsyncIOScheduler(loop)
            done = asyncio.Event()

            TangoClient() \\
                .read("sys/tg_test/1", "double_scalar") \\
                .map(lambda v: abs(v) * 2.0 + 1.5) \\
                .write("sys/tg_test/1", "double_scalar_w") \\
                .subscribe(
                    on_next=print,
                    on_completed=done.set,
                    scheduler=scheduler,
                )

            await done.wait()
    """

    def __init__(self) -> None:
        self._chain = None  # rx.Observable, built lazily

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(self, device: str, attr: str) -> TangoClient:
        """Read attribute *attr* from *device*.  The value becomes the input for the next step."""
        if self._chain is None:
            self._chain = read_attribute(device, attr)
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: read_attribute(device, attr))
            )
        return self

    # ------------------------------------------------------------------
    # monitor
    # ------------------------------------------------------------------

    def monitor(self, device: str, attr: str, event: str = "change") -> TangoClient:
        """Subscribe to Tango events for *attr* on *device* (push, multi-value).

        Can only be used as the *first* step; chaining a monitor after
        another step is not supported.
        """
        if self._chain is not None:
            raise RuntimeError("monitor() must be the first step in a TangoClient chain")
        self._chain = monitor_attribute(device, attr, event)
        return self

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(self, device: str, attr: str, value=None) -> TangoClient:
        """Write to attribute *attr* on *device*.

        *value* can be:

        - omitted / ``None`` — write the result of the previous step
        - a static value — written as-is, ignoring the previous result
        - a callable ``fn(prev) -> value`` — called with the previous result

        The written value becomes the input for the next step.
        """
        if callable(value):
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_attribute(device, attr, value(prev)))
            )
        elif value is None:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_attribute(device, attr, prev))
            )
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: write_attribute(device, attr, value))
            )
        return self

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    def execute(self, device: str, cmd: str, argin=None) -> TangoClient:
        """Execute command *cmd* on *device*.

        *argin* can be:

        - omitted / ``None`` — command is called without an argument
        - a static value — used as the command input
        - a callable ``fn(prev) -> argin`` — called with the previous result

        The command output becomes the input for the next step.
        """
        if self._chain is None:
            # First step — seed the chain directly
            static = argin(None) if callable(argin) else argin
            self._chain = execute_command(device, cmd, static)
        elif callable(argin):
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: execute_command(device, cmd, argin(prev)))
            )
        elif argin is None:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: execute_command(device, cmd))
            )
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: execute_command(device, cmd, argin))
            )
        return self

    # ------------------------------------------------------------------
    # map
    # ------------------------------------------------------------------

    def map(self, fn: Callable) -> TangoClient:
        """Apply a pure transformation to the current value without any I/O."""
        self._chain = self._chain.pipe(ops.map(fn))
        return self

    # ------------------------------------------------------------------
    # Terminal operator
    # ------------------------------------------------------------------

    def subscribe(self, on_next=None, on_error=None, on_completed=None, scheduler=None):
        """Subscribe to the chain.  Execution starts immediately.

        Returns a disposable that can be used to cancel an in-flight operation.
        """
        if self._chain is None:
            raise RuntimeError(
                "TangoClient chain is empty — add at least one step before subscribing"
            )
        return self._chain.subscribe(
            on_next=on_next,
            on_error=on_error,
            on_completed=on_completed,
            scheduler=scheduler,
        )

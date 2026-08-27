"""Fluent DectrisClient — mirrors TangoClient/EpicsClient for a SIMPLON detector."""

from __future__ import annotations

from typing import Callable

import reactivex.operators as ops

from rxdectris.command import send_command
from rxdectris.config import read_config, write_config
from rxdectris.context import DetectorContext
from rxdectris.stream import stream2


class DectrisClient:
    """Fluent builder for sequential SIMPLON operations.

    Same shape as ``TangoClient``/``EpicsClient``: each method appends a step
    to an internal Rx chain, nothing executes until ``subscribe()``, and each
    step's result becomes the next step's input. Like Tango (and unlike
    EPICS), SIMPLON has commands — ``execute()`` issues them.

    Example — read count_time, arm, trigger::

        DectrisClient(ctx) \\
            .read("count_time") \\
            .execute("arm") \\
            .execute("trigger") \\
            .subscribe(on_next=print, on_completed=done.set, scheduler=scheduler)
    """

    def __init__(self, ctx: DetectorContext) -> None:
        self._ctx = ctx
        self._chain = None  # rx.Observable, built lazily

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(self, parameter: str) -> "DectrisClient":
        """Read config *parameter*. The JSON dict becomes the input for the next step."""
        if self._chain is None:
            self._chain = read_config(parameter, self._ctx)
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: read_config(parameter, self._ctx))
            )
        return self

    # ------------------------------------------------------------------
    # monitor
    # ------------------------------------------------------------------

    def monitor(self) -> "DectrisClient":
        """Subscribe to the Stream V2 socket (push, multi-value).

        Can only be used as the *first* step; chaining a monitor after
        another step is not supported.
        """
        if self._chain is not None:
            raise RuntimeError("monitor() must be the first step in a DectrisClient chain")
        self._chain = stream2(self._ctx)
        return self

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(self, parameter: str, value=None) -> "DectrisClient":
        """Write to config *parameter*.

        *value* can be omitted/``None`` (write the previous step's result), a
        static value, or a callable ``fn(prev) -> value``.
        """
        if callable(value):
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_config(parameter, value(prev), self._ctx))
            )
        elif value is None:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: write_config(parameter, prev, self._ctx))
            )
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: write_config(parameter, value, self._ctx))
            )
        return self

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    def execute(self, command: str, argin=None) -> "DectrisClient":
        """Issue detector command *command* (``arm``, ``trigger``, ``disarm``, ...).

        *argin* can be omitted/``None``, a static value, or a callable
        ``fn(prev) -> argin``. The command's ``sequence_id`` becomes the
        input for the next step.
        """
        if self._chain is None:
            static = argin(None) if callable(argin) else argin
            self._chain = send_command(command, self._ctx, static)
        elif callable(argin):
            self._chain = self._chain.pipe(
                ops.flat_map(lambda prev: send_command(command, self._ctx, argin(prev)))
            )
        elif argin is None:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: send_command(command, self._ctx))
            )
        else:
            self._chain = self._chain.pipe(
                ops.flat_map(lambda _: send_command(command, self._ctx, argin))
            )
        return self

    # ------------------------------------------------------------------
    # map
    # ------------------------------------------------------------------

    def map(self, fn: Callable) -> "DectrisClient":
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
            raise RuntimeError("DectrisClient chain is empty — add at least one step before subscribing")
        return self._chain.subscribe(
            on_next=on_next,
            on_error=on_error,
            on_completed=on_completed,
            scheduler=scheduler,
        )

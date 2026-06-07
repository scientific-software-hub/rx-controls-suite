"""Single-shot Tango command execution as an Observable."""

import asyncio

import reactivex as rx

from rxtango.context import TangoContext


def execute_command(device: str, name: str, argin=None) -> rx.Observable:
    """Execute command *name* on *device* and emit the command result.

    *argin* is the optional input argument.  When ``None`` the command is
    called without an argument.  The command output (argout) is emitted and
    the Observable completes immediately.  On any Tango error the error
    propagates via ``on_error``.

    This is the Tango-specific primitive that has no EPICS equivalent —
    EPICS has no commands.  It mirrors ``RxTangoCommand<T, V>`` in the Java
    library.
    """

    def subscribe(observer, scheduler=None):
        async def _execute():
            try:
                loop = asyncio.get_running_loop()
                proxy = await loop.run_in_executor(None, TangoContext.get_proxy, device)
                if argin is None:
                    result = await loop.run_in_executor(None, proxy.command_inout, name)
                else:
                    result = await loop.run_in_executor(None, proxy.command_inout, name, argin)
                observer.on_next(result)
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)

        asyncio.ensure_future(_execute())

    return rx.create(subscribe)

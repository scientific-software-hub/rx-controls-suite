"""Per-update monitor failures, carried as messages rather than exceptions."""

from __future__ import annotations

import time


class PvUpdateError(Exception):
    """A single CA monitor update that failed to convert, or arrived with a
    non-normal status.

    This is an ``Exception`` subclass so it composes with code that expects
    one, but it is delivered as a *value* on :func:`monitor_errors` — never
    via ``on_error`` — because a single bad update must not terminate a
    long-lived monitor.
    """

    def __init__(self, pv_name: str, response, cause: Exception | None = None) -> None:
        self.pv_name = pv_name
        self.response = response
        self.cause = cause
        self.timestamp = time.time()
        detail = cause if cause is not None else response.status
        super().__init__(f"{pv_name}: {detail}")

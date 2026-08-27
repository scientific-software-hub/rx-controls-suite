"""Exceptions raised by the rxdectris SIMPLON wrapper."""

from __future__ import annotations

from typing import Any


class SimplonError(Exception):
    """Base error for a failed SIMPLON API call.

    Carries the HTTP status code and, where available, the parsed JSON error
    body the DCU returned — both useful when a fault-injection scenario needs
    to assert on *why* a call failed, not just that it did.
    """

    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class DetectorStateError(SimplonError):
    """Raised on an illegal state transition — e.g. ``trigger`` before ``arm``.

    Mirrors the real DCU's behaviour: an out-of-sequence command returns an
    HTTP error rather than silently no-opping.
    """


class SeriesAborted(SimplonError):
    """Raised when a series is aborted mid-acquisition.

    Fired by :func:`rxdectris.recipes.acquire_series` when the DCU reports
    ``abort`` (fault injection, upstream cancellation) rather than a clean
    ``end`` message.
    """


def _json_or_none(response) -> Any:
    """Best-effort JSON decode — SIMPLON command responses with no body are legal."""
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def raise_for_simplon_status(response) -> None:
    """Raise :class:`SimplonError` (or the more specific
    :class:`DetectorStateError` for a 409) if *response* is an HTTP error.
    """
    if response.status_code < 400:
        return
    body = _json_or_none(response)
    message = f"SIMPLON {response.request.method} {response.request.url} -> {response.status_code}"
    if response.status_code == 409:
        raise DetectorStateError(message, status_code=response.status_code, body=body)
    raise SimplonError(message, status_code=response.status_code, body=body)

"""Correlate N timestamped readings per tick, exposing their measured skew.

``rx.zip(read_a, read_b)`` gives *arrival-index* consistency — the pair is
only guaranteed to have completed together, not to describe the same
instant. ``correlate_snapshot`` zips N ``*_ts`` sources (each emitting a
``Reading``-shaped object: ``.value``, ``.ts``, ``.quality``) and computes
the actual spread between their *source* timestamps, so a consumer can see
— or bound — how stale a correlation really is instead of assuming it away.

Use this only where the values are like-typed physical quantities whose
simultaneity is the point (e.g. two beam diagnostics). A heterogeneous
"read several unrelated things this tick" zip (a dashboard snapshot) is
not a simultaneity claim and should stay a plain ``zip``.
"""

from dataclasses import dataclass
from typing import Any, Callable

import reactivex as rx
import reactivex.operators as ops


def _default_is_valid(quality: Any) -> bool:
    """Best-effort cross-package validity check.

    Recognizes caproto's ``AlarmSeverity.NO_ALARM`` and Tango's
    ``AttrQuality.ATTR_VALID`` by name, so one ``correlate_snapshot`` call
    can correlate an EPICS ``Reading`` against a Tango ``Reading`` (see
    ``examples/tango_epics_normalize.py``) without either package
    importing the other's quality enum. An unrecognized quality type is
    treated as valid — override with ``is_valid=`` for a stricter check.
    """
    name = getattr(quality, "name", None)
    return name in (None, "NO_ALARM", "ATTR_VALID")


@dataclass(frozen=True)
class Correlated:
    """N readings' values, plus their measured timestamp skew.

    ``violated`` is set when ``tolerance_s`` was exceeded or any reading's
    quality failed validity — regardless of ``on_violation``; with
    ``on_violation="drop"`` a violated tuple never reaches the subscriber
    at all, so seeing one here only happens with ``on_violation="flag"``.
    """

    values: tuple
    skew: float
    violated: bool = False


def _correlate(
    combiner,
    sources: tuple[rx.Observable, ...],
    tolerance_s: float | None,
    on_violation: str,
    is_valid: Callable[[Any], bool],
) -> rx.Observable:
    if on_violation not in ("drop", "flag"):
        raise ValueError(f"on_violation must be 'drop' or 'flag', got {on_violation!r}")

    def build(readings) -> Correlated:
        skew = max(r.ts for r in readings) - min(r.ts for r in readings)
        bad_quality = any(not is_valid(r.quality) for r in readings)
        violated = bad_quality or (tolerance_s is not None and skew > tolerance_s)
        return Correlated(values=tuple(r.value for r in readings), skew=skew, violated=violated)

    pipeline = [ops.map(build)]
    if on_violation == "drop":
        pipeline.append(ops.filter(lambda c: not c.violated))
    return combiner(*sources).pipe(*pipeline)


def correlate_snapshot(
    *sources: rx.Observable,
    tolerance_s: float | None = None,
    on_violation: str = "drop",
    is_valid: Callable[[Any], bool] = _default_is_valid,
) -> rx.Observable:
    """Zip N ``*_ts`` sources into one :class:`Correlated` per tick.

    ``skew = max(ts) - min(ts)`` across the tuple's source timestamps —
    not the time the reads completed, which ``rx.zip`` already serializes
    to "as soon as all complete" and says nothing about the moment each
    value was actually true at its source.

    If *tolerance_s* is set and the skew exceeds it, or any reading's
    quality fails *is_valid*, the tuple is either **dropped**
    (``on_violation="drop"``, the default — the tuple never reaches the
    subscriber) or **flagged** (``on_violation="flag"`` — still emitted,
    with ``Correlated.violated`` set, so the subscriber can inspect and
    act on it).
    """
    return _correlate(rx.zip, sources, tolerance_s, on_violation, is_valid)


def correlate_latest(
    *sources: rx.Observable,
    tolerance_s: float | None = None,
    on_violation: str = "flag",
    is_valid: Callable[[Any], bool] = _default_is_valid,
) -> rx.Observable:
    """``combine_latest`` version of :func:`correlate_snapshot`, for
    correlating **monitors** rather than polls.

    ``combine_latest`` has a glitch inherent to it: it emits on *either*
    source's update, with the other's last value however stale it is —
    there is no way to know from ``combine_latest`` alone whether a given
    emission is a fresh pair or one fresh value paired with a stale one.
    This turns that glitch into a *measured* one: every emission carries
    the real skew between the two sources' timestamps, and with
    *tolerance_s* set, a glitched pair is dropped or flagged exactly like
    :func:`correlate_snapshot`'s poll case.

    This is the pragmatic version, not a general fix: it does not
    time-bucket updates into aligned windows (an update at t=0.001s and
    one at t=0.002s from two independent monitors are simply two
    ``combine_latest`` emissions, each paired with whatever the other
    source's last value happened to be). True time-bucketing — grouping
    updates into aligned time windows before correlating — is a larger
    design and a follow-up, not implemented here.
    """
    return _correlate(rx.combine_latest, sources, tolerance_s, on_violation, is_valid)

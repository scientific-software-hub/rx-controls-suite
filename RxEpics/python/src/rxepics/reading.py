"""``Reading`` — a value with its source timestamp and quality.

``read_pv``/``monitor_pv`` strip everything but the bare value, so a plain
``rx.zip(read_a, read_b)`` gives *arrival-index* consistency, not *time*
consistency: two reads issued on one tick complete up to a round trip apart
against moving values, and the code has no way to even measure that skew.
``read_pv_ts``/``monitor_pv_ts`` emit :class:`Reading` instead, so a
consumer that needs to know can. See ``correlate.py`` for the operator that
turns a tuple of ``Reading``s into a measured skew.
"""

from dataclasses import dataclass
from typing import Any

from caproto import AlarmSeverity


@dataclass(frozen=True)
class Reading:
    """One value plus the moment and quality it was known to be true.

    ``ts`` is POSIX seconds from the **source** — for EPICS, the CA server's
    own ``TIME_*`` timestamp of when the value last changed, which on a
    slow-changing PV can be considerably older than the moment the read
    actually completed. ``quality`` is caproto's ``AlarmSeverity`` for this
    binding (Tango's ``Reading`` carries its own native ``AttrQuality``
    instead — the two are not interchangeable, deliberately: each carries
    the quality vocabulary its own control system actually uses).
    """

    value: Any
    ts: float
    quality: AlarmSeverity

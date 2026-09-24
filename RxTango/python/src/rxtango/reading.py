"""``Reading`` — a value with its source timestamp and quality.

``read_attribute``/``monitor_attribute`` strip everything but the bare
value, so a plain ``rx.zip(read_a, read_b)`` gives *arrival-index*
consistency, not *time* consistency: two reads issued on one tick complete
up to a round trip apart against moving values, and the code has no way to
even measure that skew. ``read_attribute_ts``/``monitor_attribute_ts`` emit
:class:`Reading` instead, so a consumer that needs to know can.
"""

from dataclasses import dataclass
from typing import Any

import tango


@dataclass(frozen=True)
class Reading:
    """One value plus the moment and quality it was known to be true.

    ``ts`` is POSIX seconds from ``DeviceAttribute.time`` (a ``TimeVal``) —
    the Tango device server's own timestamp of when the attribute last
    changed, verified via ``TimeVal.totime()`` against pytango 10.3.1.
    ``quality`` is the attribute's native ``tango.AttrQuality`` (EPICS's
    ``Reading`` carries caproto's ``AlarmSeverity`` instead — the two are
    not interchangeable, deliberately: each carries the quality vocabulary
    its own control system actually uses).
    """

    value: Any
    ts: float
    quality: "tango.AttrQuality"

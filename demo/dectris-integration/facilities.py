"""Facility health — one semantic model, two control systems underneath.

``FacilityHealth`` is the only view the DECTRIS recipes (``recipes.py``) get
of "is the facility safe to acquire into". ``TangoFacility`` derives it from
the storage ring's native Tango attributes, by importing
``demo/synchrotron-beamline/facility.py::ring_health`` **unmodified** —
that file is already the single source of truth for the ring's device
addresses and thresholds, and this module adds nothing to it, only a
`Health -> FacilityHealth` reshape. ``EpicsFacility`` derives the same shape
from the ``FAC:*`` PV mirror that ``facility_bridge.py`` maintains.

Both adapters observe **the same simulated machine** — the Tango ring — just
through two different control systems. That's what makes a run under
``--facility epics`` and a run under ``--facility tango`` a fair, provable
comparison rather than two different demos wearing the same recipe.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol

import reactivex as rx
import reactivex.operators as ops

# ── path bootstrap — mirrors demo/workflow-engines/scan_core.py ────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "demo" / "synchrotron-beamline"))

from facility import (  # noqa: E402  -- demo/synchrotron-beamline's facility.py
    MIN_BEAM_CURRENT,
    ORBIT_ALARM,
)
from facility import ring_health as _tango_ring_health  # noqa: E402
from rxepics.channel import read_pv  # noqa: E402


@dataclass(frozen=True)
class FacilityHealth:
    """The one semantic model every DECTRIS recipe gates on."""

    beam_available: bool
    interlock_ok: bool
    orbit_ok: bool
    current: float | None
    source: str  # "epics" | "tango" | "fake"


def is_healthy(h: FacilityHealth) -> bool:
    """Same gating rule as ``demo/synchrotron-beamline/facility.py::is_healthy``:
    beam + no interlock is required to acquire; orbit only degrades quality."""
    return h.beam_available and h.interlock_ok


class Facility(Protocol):
    """What a recipe needs from a facility adapter — nothing more."""

    name: str

    def health(self) -> rx.Observable:
        """Continuous, shared Observable[FacilityHealth] — never completes."""
        ...

    def snapshot(self) -> rx.Observable:
        """Single-shot Observable[FacilityHealth] — one value, then completes.
        Used for per-frame correlation (``rx.zip`` with a detector frame)."""
        ...


class _CachingFacility:
    """Shared plumbing: keep the shared ``health()`` poll subscription alive
    and cache its latest value so ``snapshot()`` (used once per frame, in
    ``recipes.py::correlate_with``) returns instantly instead of blocking
    each frame on the next poll tick — which, at a ~10ms count_time and a
    ~500ms poll interval, would make correlation the bottleneck of the whole
    acquisition rather than the detector.

    Populated as soon as construction subscribes; guaranteed non-empty by
    the time any frame needs it, because ``wait_until_healthy`` always runs
    — and therefore already observes the first tick — before the first
    frame can arrive.
    """

    def __init__(self, health: rx.Observable, scheduler) -> None:
        self._health = health
        self._latest: FacilityHealth | None = None
        self._cache_sub = health.subscribe(on_next=self._update_cache, scheduler=scheduler)

    def _update_cache(self, h: FacilityHealth) -> None:
        self._latest = h

    def health(self) -> rx.Observable:
        return self._health

    def snapshot(self) -> rx.Observable:
        if self._latest is not None:
            return rx.of(self._latest)
        return self._health.pipe(ops.take(1))


class TangoFacility(_CachingFacility):
    """Wraps ``demo/synchrotron-beamline/facility.py::ring_health`` unmodified."""

    name = "tango"

    def __init__(self, scheduler, interval_ms: int = 500) -> None:
        health = _tango_ring_health(scheduler, interval_ms).pipe(
            ops.map(_from_tango_health),
            ops.share(),
        )
        super().__init__(health, scheduler)


def _from_tango_health(h) -> FacilityHealth:
    return FacilityHealth(
        beam_available=h.current >= MIN_BEAM_CURRENT,
        interlock_ok=h.interlocks == 0,
        orbit_ok=abs(h.orbit_x) < ORBIT_ALARM,
        current=h.current,
        source="tango",
    )


class EpicsFacility(_CachingFacility):
    """Reads the ``FAC:*`` PV mirror ``facility_bridge.py`` maintains.

    Same thresholds as :class:`TangoFacility` — ``MIN_BEAM_CURRENT`` /
    ``ORBIT_ALARM`` are imported from the same ``facility.py``, not
    redefined here, so the two adapters cannot silently drift apart.
    """

    name = "epics"

    def __init__(self, ctx, scheduler, interval_ms: int = 500) -> None:
        health = rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: rx.zip(
                read_pv("FAC:CURRENT", ctx),
                read_pv("FAC:INTERLOCK", ctx),
                read_pv("FAC:ORBIT_X", ctx),
            )),
            ops.map(lambda t: FacilityHealth(
                beam_available=float(t[0]) >= MIN_BEAM_CURRENT,
                interlock_ok=int(t[1]) == 0,
                orbit_ok=abs(float(t[2])) < ORBIT_ALARM,
                current=float(t[0]),
                source="epics",
            )),
            ops.share(),
        )
        super().__init__(health, scheduler)


class FakeFacility:
    """Replays a scripted list of :class:`FacilityHealth` — no stack needed.

    Used by the adapter-invariance tests: run the same recipe against a
    canned health sequence and assert the recipe's behaviour depends only on
    the *values*, never on which real adapter produced them.
    """

    name = "fake"

    def __init__(self, script: list[FacilityHealth], scheduler=None, interval_ms: int = 200) -> None:
        self._script = script
        self._health = rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
            ops.map(lambda i: script[min(i, len(script) - 1)]),
            ops.share(),
        )

    def health(self) -> rx.Observable:
        return self._health

    def snapshot(self) -> rx.Observable:
        return rx.of(self._script[0])

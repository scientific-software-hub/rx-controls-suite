"""Reusable recipes — the vocabulary experiment.py's hero pipeline is written in.

None of these functions know whether the facility is Tango or EPICS, or
whether the series is 5 frames or 500 — that separation is the entire
demo. Each one composes ``rxdectris`` (detector) with ``facility.py``
(facility health) or ``dlab.py`` (processing) primitives.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import h5py
import numpy as np
import reactivex as rx
import reactivex.operators as ops

from facilities import FacilityHealth, is_healthy
from rxdectris.command import abort
from rxdectris.models import Frame, SeriesEnd, SeriesStart

# retry_with_backoff already lives in rxepics as a generic single-shot
# operator; re-exporting rather than reimplementing it here is itself part
# of the pitch — the natural next step is a shared `rxcore` package that
# every platform adapter (and this demo) draws generic operators from.
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))
from rxepics.retry import retry_with_backoff  # noqa: E402,F401


# ── facility gating ─────────────────────────────────────────────────────────

def wait_until_healthy(health: rx.Observable) -> rx.Observable:
    """A pure timing gate — same idiom as guarded_scan.py's ``wait_healthy``:
    filter -> take(1) -> ignore_elements(). Emits nothing, just completes
    once the facility is safe to acquire into."""
    return health.pipe(
        ops.filter(is_healthy),
        ops.take(1),
        ops.ignore_elements(),
    )


def interlock_trigger(health: rx.Observable) -> rx.Observable:
    """Fire once, with the triggering FacilityHealth, when an interlock trips."""
    return health.pipe(
        ops.filter(lambda h: not h.interlock_ok),
        ops.take(1),
    )


def abort_on(trigger: rx.Observable, ctx) -> Callable[[rx.Observable], rx.Observable]:
    """Operator: cut *source* short once *trigger* fires AND the resulting
    ``abort`` command has actually completed.

    ``take_until`` completes *source* the instant its own argument
    Observable emits — so the abort has to happen *inside* that argument
    Observable (``flat_map``), not as a fire-and-forget side effect
    (``do_action``) next to it. A fire-and-forget abort races the rest of
    the pipeline completing and the caller closing its ``DetectorContext``
    right after — which can drop the abort request before it's ever sent,
    leaving the real detector stuck mid-series. Best-effort on failure
    (``ops.catch``): the source still needs to stop even if the abort call
    itself errors.
    """

    def _op(source: rx.Observable) -> rx.Observable:
        armed_trigger = trigger.pipe(
            ops.flat_map(lambda t: abort(ctx).pipe(
                ops.map(lambda _: t),
                ops.catch(lambda e, _src: rx.of(t)),
            )),
        )
        return source.pipe(ops.take_until(armed_trigger))

    return _op


def guarded_by(health: rx.Observable, ctx) -> Callable[[rx.Observable], rx.Observable]:
    """Operator: abort the detector and stop the series the instant the
    facility's interlock trips. This is Scenario B of the demo."""
    return abort_on(interlock_trigger(health), ctx)


# ── per-frame correlation ───────────────────────────────────────────────────

@dataclass(frozen=True)
class AcquiredFrame:
    """A detector frame, stamped with the facility state at the moment it
    was correlated — provenance the SIMPLON API alone cannot give you,
    because ``image_appendix``/``user_data`` is per-series, not per-frame."""

    frame: Frame
    facility: FacilityHealth
    quality_ok: bool


def correlate_with(facility) -> Callable[[rx.Observable], rx.Observable]:
    """Operator: stamp every :class:`~rxdectris.models.Frame` with a facility
    snapshot, producing :class:`AcquiredFrame`. ``SeriesStart``/``SeriesEnd``
    pass through unchanged.

    Uses ``concat_map`` rather than ``flat_map`` deliberately: ``flat_map``
    does not preserve arrival order when its inner observables settle out of
    order, and ``SeriesEnd`` (``rx.of``, instant) would otherwise race ahead
    of a still-pending frame correlation and print out of sequence. Safe to
    serialize here because ``facility.snapshot()`` is a cached last-value
    read (see ``_CachingFacility``), not a fresh poll — so ``concat_map``
    costs no real latency per frame.
    """

    def _op(source: rx.Observable) -> rx.Observable:
        def handle(msg):
            if isinstance(msg, Frame):
                return facility.snapshot().pipe(
                    ops.map(lambda h: AcquiredFrame(
                        frame=msg, facility=h, quality_ok=is_healthy(h) and h.orbit_ok,
                    ))
                )
            return rx.of(msg)

        return source.pipe(ops.concat_map(handle))

    return _op


# ── processing stage ────────────────────────────────────────────────────────

def _check_success(result: dict) -> dict:
    if result.get("status") != "succeeded":
        raise RuntimeError(f"processing failed: {result.get('error')}")
    return result


def process_with(dlab, workflow: str, retries: int = 3) -> Callable[[rx.Observable], rx.Observable]:
    """Operator: upload -> run_job -> await_result, retried as one unit.

    Applied to an Observable of dataset summaries (e.g. one emitted by
    :class:`AcquisitionRun` on close). Retrying re-runs upload and the job —
    it never re-triggers the detector, because the detector isn't part of
    this pipeline stage at all. ``tests/test_retry_boundary.py`` is the
    assertion that this boundary actually holds.

    A D.LAB job that finishes with ``status: "failed"`` is a *value* from the
    API's own shape, not an rx error — ``await_result`` only ever calls
    ``on_error`` for a transport failure or timeout. ``retry_with_backoff``
    only ever catches exceptions, so this operator applies the same check
    ``validate_result()`` exposes *before* the retry wrapper, not after —
    otherwise a failed job would look like success to ``retry_with_backoff``
    and nothing would ever retry.
    """

    def _op(source: rx.Observable) -> rx.Observable:
        return source.pipe(
            ops.flat_map(dlab.upload),
            ops.flat_map(lambda dataset_id: dlab.run_job(dataset_id, workflow)),
            ops.flat_map(dlab.await_result),
            ops.map(_check_success),
            retry_with_backoff(max_retries=retries),
        )

    return _op


def validate_result() -> Callable[[rx.Observable], rx.Observable]:
    """Operator: raise if the D.LAB job body reports anything but success.

    ``process_with()`` already applies this same check internally (so
    retries actually retry) — this is for pipelines that consume a D.LAB
    stage directly without going through ``process_with()``.
    """
    return lambda source: source.pipe(ops.map(_check_success))


# ── HDF5 run ─────────────────────────────────────────────────────────────────
#
# Same idiom as demo/workflow-engines/scan_core.py's ScanRun (indexed writes,
# so an aborted run leaves untouched rows zero-filled) — not that class
# itself, because the compound dtype genuinely differs: this records
# detector series/image identity and per-frame facility correlation, not
# tomography projection angles.

_DTYPE = np.dtype([
    ("timestamp", "f8"),
    ("image_id", "i4"),
    ("counts", "f8"),
    ("beam_current", "f4"),
    ("beam_available", "?"),
    ("interlock_ok", "?"),
    ("orbit_ok", "?"),
    ("quality_ok", "?"),
])


class AcquisitionRun:
    """Owns the HDF5 file for one acquisition — the sink `experiment.py`
    subscribes into via ``ops.do_action`` alongside the display."""

    def __init__(self, out_dir: Path, num_frames: int, facility_source: str) -> None:
        self.path = out_dir / f"acquisition_{facility_source}_{time.strftime('%Y%m%d_%H%M%S')}.h5"
        self.file = h5py.File(self.path, "w")
        self.dataset = self.file.create_dataset("frames", shape=(num_frames,), dtype=_DTYPE)
        self.file.attrs["num_frames"] = num_frames
        self.file.attrs["facility_source"] = facility_source
        self._facility_source = facility_source
        self.frames_written = 0
        self.quality_ok_count = 0

    def write_frame(self, acquired: AcquiredFrame) -> None:
        f, h = acquired.frame, acquired.facility
        self.dataset[f.image_id] = (
            time.time(), f.image_id, f.counts,
            h.current or 0.0, h.beam_available, h.interlock_ok, h.orbit_ok,
            acquired.quality_ok,
        )
        self.frames_written += 1
        if acquired.quality_ok:
            self.quality_ok_count += 1

    def close(self) -> None:
        self.file.close()

    def summary(self) -> dict:
        """The dataset payload handed to ``dlab.upload`` once the run closes."""
        return {
            "path": str(self.path),
            "frames": self.frames_written,
            "quality_ok": self.quality_ok_count,
            "facility_source": self._facility_source,
        }

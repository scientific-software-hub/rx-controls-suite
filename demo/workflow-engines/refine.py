"""Quality-driven refinement loop — the part that makes the n8n demo a cycle,
not a straight line.

``scan_core.py`` cuts one scan into *N* contiguous sweeps so an orchestrator
can drive it as *N* visible steps. That is still a DAG: the number of steps
is known before the first frame. This module adds the piece a DAG can't
express — a decision that only exists *after* a measurement:

  - ``QualityLedger``     — remembers the last-known quality of every
    projection index across re-acquisitions (re-acquiring index 7 overwrites
    index 7's verdict; it does not append a second row).
  - ``assess``            — given the ledger, a target quality %, the current
    iteration and a cap, returns a ``RefineDecision``: stop or keep going,
    and — the distinction the demo turns on — whether stopping means
    *converged* (target met) or *exhausted* (hit the iteration cap with the
    beam still bad).
  - ``refine_points``     — turns a set of low-quality indices back into
    ``(index, angle)`` pairs so the acquisition re-runs *those* projections
    at *their* original angles and writes them to *their* original HDF5 rows.

Like ``scan_core.py`` this module has **no** orchestrator import and no rx
import — it's pure bookkeeping, unit-tested against a hand-built ledger with
no SCADA and no event loop. A future Prefect-side refinement variant would
reuse it unchanged.

The angle grid here is deliberately the same formula as
``scan_core.sweep_angles`` (``test_refine.py`` asserts they agree); it's
duplicated rather than imported only to keep this module free of the
``facility``/``rxtango`` import chain ``scan_core`` pulls in.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── the angle grid (must match scan_core.sweep_angles) ──────────────────────

def angle_grid(num_proj: int, start: float = 0.0, stop: float = 180.0) -> list[float]:
    """The full list of projection angles — identical to the flattening of
    ``scan_core.sweep_angles(num_proj, k)`` for any *k*."""
    step = (stop - start) / max(num_proj - 1, 1)
    return [start + i * step for i in range(num_proj)]


def refine_points(
    indices: list[int], num_proj: int, start: float = 0.0, stop: float = 180.0,
) -> list[tuple[int, float]]:
    """Map low-quality projection *indices* to ``(index, angle)`` pairs.

    The index is preserved so the re-acquired frame overwrites its original
    HDF5 row (``ScanRun.write_frame`` indexes by ``proj_index``) and the
    ledger overwrites its original verdict — a refine pass changes existing
    rows, it never grows the dataset.
    """
    grid = angle_grid(num_proj, start, stop)
    return [(i, grid[i]) for i in sorted(indices)]


# ── the per-index quality ledger ────────────────────────────────────────────

class QualityLedger:
    """Last-known quality of every acquired projection index.

    ``record(index, ok)`` is idempotent per index: acquiring index 7 twice
    leaves one entry, whose value is the *most recent* acquisition's verdict.
    This is what lets a second pass actually clear a LOW row instead of
    stacking a second one next to it.
    """

    def __init__(self, num_proj: int):
        self.num_proj = num_proj
        self._quality: dict[int, bool] = {}
        self._reacquired: set[int] = set()

    def record(self, index: int, quality_ok: bool) -> None:
        index = int(index)
        if index in self._quality:
            self._reacquired.add(index)
        self._quality[index] = bool(quality_ok)

    def record_frame(self, frame: tuple) -> None:
        """Convenience for the 9-tuple ``guarded_acquire_projection`` emits:
        ``(ts, index, angle, counts, bpx, bpy, ring_current, orbit_x, quality_ok)``."""
        self.record(frame[1], frame[8])

    @property
    def acquired_count(self) -> int:
        return len(self._quality)

    @property
    def fully_acquired(self) -> bool:
        return len(self._quality) >= self.num_proj

    @property
    def ok_count(self) -> int:
        return sum(1 for v in self._quality.values() if v)

    @property
    def low_count(self) -> int:
        return sum(1 for v in self._quality.values() if not v)

    @property
    def quality_pct(self) -> float:
        """OK projections as a percentage of the *whole* scan, not just of
        what's acquired so far — so a scan that's only half-acquired can't
        report 100 %."""
        return 100.0 * self.ok_count / max(self.num_proj, 1)

    def retry_indices(self) -> list[int]:
        """Acquired indices whose last verdict was LOW, sorted ascending."""
        return sorted(i for i, ok in self._quality.items() if not ok)

    def coverage(self) -> list[int]:
        """One status code per projection index, for the dashboard strip:
        ``0`` not acquired · ``1`` OK · ``2`` LOW · ``3`` OK after a
        re-acquisition (a LOW row the refinement loop cleared)."""
        out = [0] * self.num_proj
        for i, ok in self._quality.items():
            if 0 <= i < self.num_proj:
                out[i] = (3 if ok and i in self._reacquired else 1 if ok else 2)
        return out


# ── the decision ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RefineDecision:
    """What ``assess`` decided. ``stop`` and ``converged`` are separate on
    purpose: ``stop=True, converged=False`` is the honest "we hit the cap
    with the beam still out of spec" outcome the demo shows for a held
    ``orbit_drift``."""
    stop: bool
    converged: bool
    reason: str
    quality_pct: float
    iteration: int
    retry_indices: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "stop": self.stop,
            "converged": self.converged,
            "reason": self.reason,
            "quality_pct": round(self.quality_pct, 1),
            "iteration": self.iteration,
            "retry_count": len(self.retry_indices),
            "retry_indices": list(self.retry_indices),
        }


def assess(
    ledger: QualityLedger, *, target_pct: float, iteration: int, max_iterations: int,
) -> RefineDecision:
    """Decide whether the refinement loop keeps going after a full pass.

    Order of checks matters:
      1. Every projection acquired and none LOW  → converged.
      2. Every projection acquired and quality % ≥ target → converged
         (a few LOW frames are tolerable if the target allows).
      3. Iteration cap reached → stop, *not* converged — reported as such.
      4. Otherwise → keep refining the LOW indices.
    """
    retry = ledger.retry_indices()
    pct = ledger.quality_pct

    if ledger.fully_acquired and not retry:
        return RefineDecision(
            stop=True, converged=True,
            reason="all projections meet the orbit-quality spec",
            quality_pct=pct, iteration=iteration, retry_indices=[],
        )
    if ledger.fully_acquired and pct >= target_pct:
        return RefineDecision(
            stop=True, converged=True,
            reason=f"quality {pct:.0f}% ≥ target {target_pct:.0f}%",
            quality_pct=pct, iteration=iteration, retry_indices=retry,
        )
    if iteration >= max_iterations:
        return RefineDecision(
            stop=True, converged=False,
            reason=(
                f"stopped at iteration cap ({max_iterations}) with quality "
                f"{pct:.0f}% < target {target_pct:.0f}% — "
                f"{len(retry)} projection(s) still LOW"
            ),
            quality_pct=pct, iteration=iteration, retry_indices=retry,
        )
    return RefineDecision(
        stop=False, converged=False,
        reason=(
            f"quality {pct:.0f}% < target {target_pct:.0f}% — "
            f"re-acquiring {len(retry)} projection(s)"
        ),
        quality_pct=pct, iteration=iteration, retry_indices=retry,
    )

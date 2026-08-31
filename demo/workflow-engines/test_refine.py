"""Unit tests for refine.py — no SCADA, no event loop, no rx.

Same "runs anywhere" convention as test_scan_core.py, but simpler: refine.py
is pure bookkeeping, so these are plain assertions against a hand-built
ledger.

Run with:
    uv run --with pytest pytest test_refine.py -v
"""

from refine import (
    QualityLedger, RefineDecision, angle_grid, assess, refine_points,
)


# ---------------------------------------------------------------------------
# angle_grid / refine_points — must agree with scan_core.sweep_angles
# ---------------------------------------------------------------------------

class TestAngleGrid:

    def test_matches_sweep_angles_flattened(self):
        # imported lazily so a missing rxtango/PyTango install fails only this
        # one test, not the whole module (scan_core pulls in the facility chain)
        from scan_core import sweep_angles
        for num_proj, sweeps in [(36, 3), (10, 3), (1, 1), (7, 7), (50, 4)]:
            flat = [a for s in sweep_angles(num_proj, sweeps) for a in s]
            assert flat == angle_grid(num_proj), (num_proj, sweeps)

    def test_endpoints(self):
        grid = angle_grid(36, 0.0, 180.0)
        assert grid[0] == 0.0
        assert grid[-1] == 180.0

    def test_refine_points_preserves_index_and_sorts(self):
        pts = refine_points([5, 1, 30], 36)
        assert [i for i, _ in pts] == [1, 5, 30]
        grid = angle_grid(36)
        assert [a for _, a in pts] == [grid[1], grid[5], grid[30]]


# ---------------------------------------------------------------------------
# QualityLedger — idempotent per index, whole-scan denominator
# ---------------------------------------------------------------------------

class TestQualityLedger:

    def test_record_is_idempotent_per_index(self):
        led = QualityLedger(num_proj=10)
        led.record(3, False)
        led.record(3, False)
        assert led.acquired_count == 1
        assert led.retry_indices() == [3]

    def test_re_acquisition_overwrites_verdict(self):
        led = QualityLedger(num_proj=10)
        led.record(3, False)
        assert led.retry_indices() == [3]
        led.record(3, True)          # second pass clears it
        assert led.retry_indices() == []
        assert led.ok_count == 1
        assert led.low_count == 0

    def test_quality_pct_is_over_whole_scan_not_acquired(self):
        led = QualityLedger(num_proj=10)
        for i in range(5):
            led.record(i, True)      # 5/10 acquired, all OK
        assert led.quality_pct == 50.0
        assert not led.fully_acquired

    def test_record_frame_reads_the_9_tuple(self):
        led = QualityLedger(num_proj=4)
        # (ts, index, angle, counts, bpx, bpy, ring_current, orbit_x, quality_ok)
        led.record_frame((123.0, 2, 90.0, 9000.0, 0.0, 0.0, 100.0, 80.0, False))
        assert led.retry_indices() == [2]

    def test_retry_indices_sorted(self):
        led = QualityLedger(num_proj=20)
        for i in (12, 3, 7, 1):
            led.record(i, False)
        led.record(5, True)
        assert led.retry_indices() == [1, 3, 7, 12]


# ---------------------------------------------------------------------------
# assess — the stop / converged / exhausted decision
# ---------------------------------------------------------------------------

class TestAssess:

    def _full(self, num_proj, low_indices):
        led = QualityLedger(num_proj)
        for i in range(num_proj):
            led.record(i, i not in low_indices)
        return led

    def test_first_pass_all_ok_converges(self):
        led = self._full(12, low_indices=[])
        d = assess(led, target_pct=90.0, iteration=1, max_iterations=4)
        assert d.stop and d.converged
        assert d.retry_indices == []

    def test_some_low_below_target_keeps_going(self):
        led = self._full(20, low_indices=[2, 5, 9, 11, 14])  # 75 % OK
        d = assess(led, target_pct=90.0, iteration=1, max_iterations=4)
        assert not d.stop and not d.converged
        assert d.retry_indices == [2, 5, 9, 11, 14]
        assert 74.9 < d.quality_pct < 75.1

    def test_some_low_but_target_met_converges(self):
        led = self._full(20, low_indices=[3])  # 95 % OK
        d = assess(led, target_pct=90.0, iteration=2, max_iterations=4)
        assert d.stop and d.converged
        # retry list still reported even though we converged — informational
        assert d.retry_indices == [3]

    def test_iteration_cap_stops_without_converging(self):
        led = self._full(20, low_indices=[2, 5, 9, 11, 14])  # still 75 %
        d = assess(led, target_pct=90.0, iteration=4, max_iterations=4)
        assert d.stop and not d.converged
        assert "cap" in d.reason
        assert d.retry_indices == [2, 5, 9, 11, 14]

    def test_incomplete_scan_never_converges_even_at_100pct_of_acquired(self):
        led = QualityLedger(20)
        for i in range(10):
            led.record(i, True)      # 10/20, all OK -> 50 % of whole scan
        d = assess(led, target_pct=40.0, iteration=1, max_iterations=4)
        # quality_pct 50 >= target 40, BUT not fully acquired -> keep going
        assert not d.stop

    def test_decision_as_dict_shape(self):
        led = self._full(10, low_indices=[1, 2])
        d = assess(led, target_pct=90.0, iteration=1, max_iterations=3)
        out = d.as_dict()
        assert set(out) == {
            "stop", "converged", "reason", "quality_pct",
            "iteration", "retry_count", "retry_indices",
        }
        assert out["retry_count"] == 2
        assert out["retry_indices"] == [1, 2]

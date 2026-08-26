"""Unit tests for scan_core.py — no SCADA required.

Uses ``reactivex.testing.TestScheduler`` virtual time, same convention as
``RxTango/python/tests/test_operators.py``.

Run with:
    uv run --with pytest pytest test_scan_core.py -v
"""

from reactivex.testing import ReactiveTest, TestScheduler

from scan_core import (
    Health, MIN_BEAM_CURRENT, interlock_trigger, sustained_low, sweep_angles, to_events,
)


def _events(messages):
    """Extract on_next ScanEvent values from a list of Recorded messages."""
    return [m.value.value for m in messages if m.value.kind == "N"]


# ---------------------------------------------------------------------------
# sweep_angles — pure function, no scheduler
# ---------------------------------------------------------------------------

class TestSweepAngles:

    def test_even_split_has_no_gaps_or_repeats(self):
        sweeps = sweep_angles(36, 3)
        assert [len(s) for s in sweeps] == [12, 12, 12]
        flat = [a for sweep in sweeps for a in sweep]
        assert flat == sweep_angles(36, 1)[0]

    def test_uneven_split_differs_by_at_most_one_and_covers_every_angle(self):
        sweeps = sweep_angles(10, 3)
        sizes = [len(s) for s in sweeps]
        assert sum(sizes) == 10
        assert max(sizes) - min(sizes) <= 1
        flat = [a for sweep in sweeps for a in sweep]
        assert flat == sweep_angles(10, 1)[0]


# ---------------------------------------------------------------------------
# to_events — beam_low / beam_ok only on transitions, interlock carries count
# ---------------------------------------------------------------------------

class TestToEvents:

    def test_beam_events_only_on_transitions(self):
        scheduler = TestScheduler()
        above = MIN_BEAM_CURRENT + 10
        below = MIN_BEAM_CURRENT - 10

        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=above, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(220, Health(current=above, interlocks=0, orbit_x=0.0)),  # no change
            ReactiveTest.on_next(230, Health(current=below, interlocks=0, orbit_x=0.0)),  # -> beam_low
            ReactiveTest.on_next(240, Health(current=below, interlocks=0, orbit_x=0.0)),  # no change
            ReactiveTest.on_next(250, Health(current=above, interlocks=0, orbit_x=0.0)),  # -> beam_ok
        )
        # completes well after every health transition under test below —
        # to_events() cuts its output the instant frames completes (see its
        # docstring), so this must outlast the scenario, not race it
        frames = scheduler.create_cold_observable(ReactiveTest.on_completed(500))

        result = scheduler.start(lambda: to_events(frames, health))

        kinds = [ev.kind for ev in _events(result.messages)]
        assert kinds == ["beam_ok", "beam_low", "beam_ok"]

    def test_interlock_event_carries_count(self):
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(
                210, Health(current=MIN_BEAM_CURRENT + 10, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(
                230, Health(current=MIN_BEAM_CURRENT + 10, interlocks=2, orbit_x=0.0)),
        )
        # completes well after every health transition under test below —
        # to_events() cuts its output the instant frames completes (see its
        # docstring), so this must outlast the scenario, not race it
        frames = scheduler.create_cold_observable(ReactiveTest.on_completed(500))

        result = scheduler.start(lambda: to_events(frames, health))

        interlocks = [ev for ev in _events(result.messages) if ev.kind == "interlock"]
        assert len(interlocks) == 1
        assert interlocks[0].payload["interlocks"] == 2

    def test_completes_when_frames_completes_even_though_health_never_does(self):
        """Regression test: health (ring_health's poll) never completes on
        its own — a to_events() built as a bare rx.merge of frame/beam/
        interlock branches would then never complete either, and anything
        blocking on its on_completed (e.g. rx_prefect.drain) would hang
        forever after the last frame, not just after the scan. See
        to_events()'s docstring for the take_until fix."""
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=100.0, interlocks=0, orbit_x=0.0)),
        )
        frames = scheduler.create_cold_observable(
            ReactiveTest.on_next(20, (0.0, 0, 0.0, 1.0, 0.0, 0.0, 100.0, 0.0, True)),
            ReactiveTest.on_completed(30),
        )

        result = scheduler.start(lambda: to_events(frames, health))

        completions = [m for m in result.messages if m.value.kind == "C"]
        assert len(completions) == 1
        assert completions[0].time == 230  # 200 (subscribe) + 30 (frames' own completion)


# ---------------------------------------------------------------------------
# interlock_trigger — fires once, with the triggering Health
# ---------------------------------------------------------------------------

class TestInterlockTrigger:

    def test_fires_once_only(self):
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=100.0, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(220, Health(current=100.0, interlocks=1, orbit_x=0.0)),
            ReactiveTest.on_next(230, Health(current=100.0, interlocks=2, orbit_x=0.0)),
        )
        result = scheduler.start(lambda: interlock_trigger(health))

        values = _events(result.messages)
        assert len(values) == 1
        assert values[0].interlocks == 1


# ---------------------------------------------------------------------------
# sustained_low — the tier-2 beam-loss watchdog
# ---------------------------------------------------------------------------

class TestSustainedLow:

    def test_fires_after_seconds_of_continuous_low(self):
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=100.0, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(300, Health(current=10.0, interlocks=0, orbit_x=0.0)),  # low
        )
        result = scheduler.start(
            lambda: sustained_low(health, seconds=5, scheduler=scheduler),
        )

        assert len(result.messages) == 2  # one on_next, then on_completed
        assert result.messages[0].value.kind == "N"
        assert result.messages[0].time == 305  # fires exactly `seconds` after the drop

    def test_brief_flicker_does_not_fire(self):
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=100.0, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(300, Health(current=10.0, interlocks=0, orbit_x=0.0)),   # low
            ReactiveTest.on_next(302, Health(current=100.0, interlocks=0, orbit_x=0.0)),  # recovers
        )
        result = scheduler.start(
            lambda: sustained_low(health, seconds=5, scheduler=scheduler),
        )

        assert result.messages == []

    def test_sustained_after_flicker_still_fires(self):
        scheduler = TestScheduler()
        health = scheduler.create_hot_observable(
            ReactiveTest.on_next(210, Health(current=100.0, interlocks=0, orbit_x=0.0)),
            ReactiveTest.on_next(300, Health(current=10.0, interlocks=0, orbit_x=0.0)),   # low
            ReactiveTest.on_next(302, Health(current=100.0, interlocks=0, orbit_x=0.0)),  # flicker recovers
            ReactiveTest.on_next(500, Health(current=10.0, interlocks=0, orbit_x=0.0)),   # low again, sustained
        )
        result = scheduler.start(
            lambda: sustained_low(health, seconds=5, scheduler=scheduler),
        )

        assert len(result.messages) == 2
        assert result.messages[0].time == 505  # 500 + 5, not confused by the earlier flicker

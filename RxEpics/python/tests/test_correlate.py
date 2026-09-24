"""Tests for correlate_snapshot / correlate_latest — measured-skew correlation."""

import pytest
from reactivex.testing import ReactiveTest, TestScheduler

from rxepics.correlate import correlate_snapshot, correlate_latest, Correlated
from rxepics.reading import Reading

on_next = ReactiveTest.on_next
on_completed = ReactiveTest.on_completed


def _values(messages):
    return [m.value.value for m in messages if m.value.kind == "N"]


def test_skew_is_computed_from_source_timestamps_not_arrival_order():
    scheduler = TestScheduler()
    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=None)),
        on_completed(20),
    )
    ys = scheduler.create_cold_observable(
        on_next(15, Reading(value=2.0, ts=100.4, quality=None)),
        on_completed(25),
    )

    def create():
        return correlate_snapshot(xs, ys)

    result = scheduler.start(create)
    values = _values(result.messages)
    assert len(values) == 1
    c = values[0]
    assert isinstance(c, Correlated)
    assert c.values == (1.0, 2.0)
    assert c.skew == pytest.approx(0.4)
    assert c.violated is False


def test_tolerance_drops_violating_tuple_by_default():
    scheduler = TestScheduler()
    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=None)),
        on_completed(20),
    )
    ys = scheduler.create_cold_observable(
        on_next(15, Reading(value=2.0, ts=101.0, quality=None)),  # 1.0s skew
        on_completed(25),
    )

    def create():
        return correlate_snapshot(xs, ys, tolerance_s=0.5)

    result = scheduler.start(create)
    assert _values(result.messages) == []  # dropped, never reaches the subscriber


def test_tolerance_flags_instead_of_dropping():
    scheduler = TestScheduler()
    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=None)),
        on_completed(20),
    )
    ys = scheduler.create_cold_observable(
        on_next(15, Reading(value=2.0, ts=101.0, quality=None)),
        on_completed(25),
    )

    def create():
        return correlate_snapshot(xs, ys, tolerance_s=0.5, on_violation="flag")

    result = scheduler.start(create)
    values = _values(result.messages)
    assert len(values) == 1
    assert values[0].violated is True
    assert values[0].values == (1.0, 2.0)


def test_invalid_quality_drops_regardless_of_tolerance():
    scheduler = TestScheduler()

    class BadQuality:
        name = "INVALID_ALARM"

    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=BadQuality())),
        on_completed(20),
    )
    ys = scheduler.create_cold_observable(
        on_next(15, Reading(value=2.0, ts=100.0, quality=None)),
        on_completed(25),
    )

    def create():
        return correlate_snapshot(xs, ys)  # no tolerance_s set at all

    result = scheduler.start(create)
    assert _values(result.messages) == []


def test_valid_quality_by_name_across_packages():
    """The default is_valid recognizes both caproto's and Tango's 'valid'
    spelling by name, without importing either enum."""
    scheduler = TestScheduler()

    class CaprotoLikeValid:
        name = "NO_ALARM"

    class TangoLikeValid:
        name = "ATTR_VALID"

    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=CaprotoLikeValid())),
        on_completed(20),
    )
    ys = scheduler.create_cold_observable(
        on_next(15, Reading(value=2.0, ts=100.0, quality=TangoLikeValid())),
        on_completed(25),
    )

    def create():
        return correlate_snapshot(xs, ys)

    result = scheduler.start(create)
    values = _values(result.messages)
    assert len(values) == 1
    assert values[0].violated is False


def test_correlate_latest_measures_combine_latest_glitch():
    """combine_latest pairs whatever's freshest from each side; the skew
    exposes how stale the resulting pair actually is."""
    scheduler = TestScheduler()
    xs = scheduler.create_cold_observable(
        on_next(10, Reading(value=1.0, ts=100.0, quality=None)),
        on_next(50, Reading(value=1.5, ts=100.5, quality=None)),
        on_completed(60),
    )
    ys = scheduler.create_cold_observable(
        on_next(20, Reading(value=2.0, ts=100.05, quality=None)),
        on_completed(60),
    )

    def create():
        return correlate_latest(xs, ys, on_violation="flag")

    result = scheduler.start(create)
    values = _values(result.messages)
    # emits once per source update: at t=20 (x=1.0,y=2.0) and t=50 (x=1.5,y=2.0)
    assert len(values) == 2
    assert values[0].values == (1.0, 2.0)
    assert values[0].skew == pytest.approx(0.05)
    assert values[1].values == (1.5, 2.0)
    assert values[1].skew == pytest.approx(0.45)

"""The interpolation rules a buffered game-log line is placed with."""

from __future__ import annotations

import pytest

from brake_trainer.timeline import HistoryPoint, PositionTimeline


def _timeline(*points: tuple[float, float, int]) -> PositionTimeline:
    timeline = PositionTimeline(keep_s=300.0)
    for t, pos, lap in points:
        timeline.append(HistoryPoint(t, pos, 200.0, False, lap))
    return timeline


def test_at_interpolates_between_the_samples_around_the_time():
    timeline = _timeline((1.0, 0.20, 4), (2.0, 0.21, 4))
    found = timeline.at(1.5)
    assert found is not None
    assert (found.t, found.pos, found.lap) == (1.5, pytest.approx(0.205), 4)


def test_at_does_not_interpolate_backwards_across_the_start_finish_line():
    # Within one lap number, 0.02 -> 0.98 is a backwards wrap (a reset, or the car crossing the
    # line the wrong way), not driving forwards. Interpolating at three quarters of the frame
    # would put the car at 0.99, in a sector it has not driven yet; the earlier sample is where
    # the event happened.
    timeline = _timeline((1.0, 0.02, 5), (2.0, 0.98, 5))
    found = timeline.at(1.75)
    assert found is not None
    assert (found.pos, found.lap) == (0.02, 5)


def test_at_does_not_interpolate_forwards_across_the_start_finish_line():
    timeline = _timeline((1.0, 0.98, 5), (2.0, 0.02, 5))
    found = timeline.at(1.75)
    assert found is not None
    assert (found.pos, found.lap) == (0.98, 5)


def test_at_falls_back_to_the_earlier_sample_across_a_teleport():
    timeline = _timeline((1.0, 0.30, 5), (2.0, 0.45, 5))
    found = timeline.at(1.5)
    assert found is not None
    assert found.pos == 0.30


def test_at_labels_the_seam_after_the_line_with_the_new_lap():
    # The sample taken in the frame that wraps the line still carries the old lap number. A time
    # between it and the next sample belongs to the new lap, so the label comes from the later one.
    timeline = _timeline((1.0, 0.98, 4), (2.0, 0.02, 4), (3.0, 0.04, 5))
    found = timeline.at(2.5)
    assert found is not None
    assert (found.pos, found.lap) == (pytest.approx(0.03), 5)


def test_lap_start_finds_the_wrap_sample_that_still_carries_the_old_lap():
    # The first sample labelled with the new lap is one after the wrap, so the crossing lies
    # between the two samples before it.
    timeline = _timeline((10.0, 0.98, 4), (10.1, 0.01, 4), (10.2, 0.02, 5))
    assert timeline.lap_start(5) == pytest.approx(10.0 + 0.1 * (0.02 / 0.03))


def test_crossing_returns_none_when_the_crossing_is_no_longer_kept():
    timeline = _timeline((10.0, 0.40, 4), (11.0, 0.50, 4))
    assert timeline.crossing(4, 0.45) == pytest.approx(10.5)
    assert timeline.crossing(3, 0.45) is None

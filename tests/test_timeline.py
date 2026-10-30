"""The interpolation rules a buffered game-log line is placed with."""

from __future__ import annotations

import pytest

from brake_trainer.timeline import CarAt, HistoryPoint, PositionTimeline


def _timeline(*points: tuple[float, float, int]) -> PositionTimeline:
    timeline = PositionTimeline(keep_s=300.0)
    for t, pos, lap in points:
        timeline.append(HistoryPoint(t, pos, 200.0, False, lap))
    return timeline


def test_at_interpolates_between_the_samples_around_the_time():
    timeline = _timeline((1.0, 0.20, 4), (2.0, 0.21, 4))
    found = timeline.at(1.5)
    assert found is not None
    assert found.t == 1.5
    assert found.pos == pytest.approx(0.205)
    assert found.lap == 4


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
    assert found.pos == pytest.approx(0.03)
    assert found.lap == 5


def test_lap_start_finds_the_wrap_sample_that_still_carries_the_old_lap():
    # The first sample labelled with the new lap is one after the wrap, so the crossing lies
    # between the two samples before it.
    timeline = _timeline((10.0, 0.98, 4), (10.1, 0.01, 4), (10.2, 0.02, 5))
    assert timeline.lap_start(5) == pytest.approx(10.0 + 0.1 * (0.02 / 0.03))


def test_crossing_returns_none_when_the_crossing_is_no_longer_kept():
    timeline = _timeline((10.0, 0.44, 4), (11.0, 0.46, 4))
    assert timeline.crossing(4, 0.45) == pytest.approx(10.5)
    assert timeline.crossing(3, 0.45) is None


def test_crossing_does_not_invent_a_time_across_a_forward_teleport():
    # A reset or teleport from 0.20 to 0.80 in one frame is not a pass through 0.45: the car never
    # drove it, so interpolating there would file a run under a time that never happened.
    timeline = _timeline((1.0, 0.20, 4), (2.0, 0.80, 4))
    assert timeline.crossing(4, 0.45) is None


def test_crossing_does_not_invent_a_time_across_a_backward_teleport():
    timeline = _timeline((1.0, 0.80, 4), (2.0, 0.20, 4))
    assert timeline.crossing(4, 0.45) is None


def test_crossing_keeps_a_normal_fast_crossing_below_the_jump_limit():
    # The guard is for teleports, not for a fast car: a move this side of JUMP_LAP still crosses.
    timeline = _timeline((1.0, 0.20, 4), (2.0, 0.24, 4))
    assert timeline.crossing(4, 0.22) == pytest.approx(1.5)


def test_at_does_not_interpolate_across_a_reset_to_an_earlier_lap():
    # Position and lap both go backwards: a reset, not a start/finish crossing.
    timeline = _timeline((1.0, 0.40, 7), (2.0, 0.10, 3))
    found = timeline.at(1.5)
    assert found is not None
    assert (found.pos, found.lap) == (0.40, 7)


def test_at_uses_the_current_car_for_a_future_timestamp():
    timeline = _timeline((1.0, 0.20, 4), (2.0, 0.30, 4))
    latest = CarAt(2.5, 0.55, 250.0, False, 5)

    assert timeline.at(2.5, latest) is latest

    # Without a current car, a future time falls back to the newest sample, not an extrapolation.
    found = timeline.at(3.0)
    assert found is not None
    assert (found.pos, found.lap) == (0.30, 4)


def test_at_returns_none_before_the_kept_history():
    timeline = _timeline((10.0, 0.20, 4), (11.0, 0.30, 4))
    assert timeline.at(9.0) is None


def test_crossing_on_the_start_finish_line_uses_the_wrap():
    timeline = _timeline((1.0, 0.98, 4), (2.0, 0.02, 4), (3.0, 0.04, 5))
    assert timeline.crossing(5, 0.0) == pytest.approx(timeline.lap_start(5))

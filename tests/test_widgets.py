"""Geometry of the sector bar."""

from __future__ import annotations

import pytest

from brake_trainer.ui.widgets import sector_rects

WIDTH = 300.0


def _boundaries(*inner: float) -> tuple[float, ...]:
    return (0.0, *inner, 1.0)


def _boundary(rects: list[tuple[float, float]], index: int) -> float:
    """Where the gap between segment ``index - 1`` and ``index`` is centred."""
    left, width = rects[index - 1]
    return (left + width + rects[index][0]) / 2


def test_sector_boundaries_follow_the_games_unequal_lines():
    # Red Bull Ring: S1 ends at 26.09% and S2 at 65.77% of the lap, not at equal thirds.
    rects = sector_rects(3, _boundaries(0.2609, 0.6577), WIDTH)
    assert _boundary(rects, 1) == pytest.approx(WIDTH * 0.2609)
    assert _boundary(rects, 2) == pytest.approx(WIDTH * 0.6577)


def test_sector_boundaries_are_equal_thirds_while_the_lines_are_unknown():
    rects = sector_rects(3, (), WIDTH)
    assert _boundary(rects, 1) == pytest.approx(WIDTH / 3)
    assert _boundary(rects, 2) == pytest.approx(2 * WIDTH / 3)
    # The outer segments take half a gap on one side, the middle one on both.
    assert rects[0][1] == pytest.approx(WIDTH / 3 - 4.0)
    assert rects[1][1] == pytest.approx(WIDTH / 3 - 8.0)
    assert rects[2][1] == pytest.approx(WIDTH / 3 - 4.0)


@pytest.mark.parametrize(
    "boundaries",
    [
        (),
        (0.0, 0.5, 1.0),  # too few
        (0.0, 0.7, 0.3, 1.0),  # not in lap order
        (0.0, 0.4, 0.4, 1.0),  # two lines at the same place
    ],
)
def test_unusable_lines_fall_back_to_equal_segments(boundaries):
    expected = sector_rects(3, (), WIDTH)
    assert sector_rects(3, boundaries, WIDTH) == expected


def test_a_sector_too_short_for_the_gap_does_not_get_a_negative_width():
    rects = sector_rects(3, _boundaries(0.005, 0.5), WIDTH)
    assert all(width >= 0.0 for _, width in rects)


def test_a_single_sector_spans_the_whole_bar():
    assert sector_rects(1, (0.0, 1.0), WIDTH) == [(0.0, WIDTH)]
    assert sector_rects(0, (), WIDTH) == []

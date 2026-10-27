"""Geometry of the sector bar."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPalette

from brake_trainer.ui import theme
from brake_trainer.ui.widgets import sector_rects

WIDTH = 300.0


def _boundaries(*inner: float) -> tuple[float, ...]:
    return (0.0, *inner, 1.0)


def _boundary(rects: list[tuple[float, float]], index: int) -> float:
    """Where sector ``index - 1`` ends and sector ``index`` starts."""
    left, width = rects[index - 1]
    return (left + width + rects[index][0]) / 2


def test_the_palette_matches_the_dark_theme():
    palette = theme.palette()

    assert palette.color(QPalette.ColorRole.Window).name() == theme.BG
    assert palette.color(QPalette.ColorRole.Base).name() == theme.BG
    assert palette.color(QPalette.ColorRole.Highlight).name() == theme.ACCENT
    assert palette.color(QPalette.ColorRole.HighlightedText).name() == theme.BUTTON_TEXT


def test_the_overlay_palette_is_pinned_to_the_existing_look():
    # These constants only centralise literals; the values are what the HUD shipped with, so the
    # refactor cannot change the look. Rendering itself is checked by eye at 1.00 and 1.50.
    assert theme.SHADOW == (0, 0, 0, 230)
    assert theme.OVERLAY_BG == (12, 14, 18)
    assert theme.TEXT_DIM_RGBA == (255, 255, 255, 175)
    assert theme.TEXT_DIM == "rgba(255, 255, 255, 175)"
    assert theme.BAR_TRACK == (0, 0, 0, 120)
    assert theme.BAR_PROGRESS == (255, 255, 255, 110)
    assert theme.BAR_OUTLINE == (255, 255, 255, 230)
    assert theme.BAR_SEPARATOR == (0, 0, 0, 170)


def test_sector_boundaries_follow_the_games_unequal_lines():
    # Red Bull Ring: S1 ends at 26.09% and S2 at 65.77% of the lap, not at equal thirds.
    rects = sector_rects(3, _boundaries(0.2609, 0.6577), WIDTH)
    assert _boundary(rects, 1) == pytest.approx(WIDTH * 0.2609)
    assert _boundary(rects, 2) == pytest.approx(WIDTH * 0.6577)


def test_sectors_meet_exactly_on_the_line_with_no_dead_zone():
    # A gap leaves a stretch where neither sector is shown. On the old 272 px bar it was 8 px =
    # 2.9% of the lap, 170 m at Monza, and both braking points fell inside it.
    rects = sector_rects(3, _boundaries(0.336448, 0.656731), WIDTH)
    assert rects[0][0] == 0.0
    assert rects[0][0] + rects[0][1] == pytest.approx(rects[1][0])
    assert rects[1][0] + rects[1][1] == pytest.approx(rects[2][0])
    assert rects[2][0] + rects[2][1] == pytest.approx(WIDTH)


def test_monza_braking_points_fall_inside_the_sector_they_start():
    # The game's lines are 41 m and 11 m before the Roggia and Ascari braking points. The old gap
    # swallowed both, so the bar showed neither sector exactly when the driver braked.
    rects = sector_rects(3, _boundaries(0.33644832163172367, 0.6567313191597194), WIDTH)
    for pos, expected in ((0.3435, 1), (0.65857, 2)):
        x = pos * WIDTH
        assert [i for i, (left, width) in enumerate(rects) if left <= x <= left + width] == [
            expected
        ]


def test_sector_boundaries_are_equal_thirds_while_the_lines_are_unknown():
    rects = sector_rects(3, (), WIDTH)
    assert [width for _, width in rects] == pytest.approx([WIDTH / 3] * 3)
    assert _boundary(rects, 1) == pytest.approx(WIDTH / 3)
    assert _boundary(rects, 2) == pytest.approx(2 * WIDTH / 3)


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


def test_a_very_short_sector_still_has_a_non_negative_width():
    rects = sector_rects(3, _boundaries(0.005, 0.5), WIDTH)
    assert all(width >= 0.0 for _, width in rects)


def test_a_single_sector_spans_the_whole_bar():
    assert sector_rects(1, (0.0, 1.0), WIDTH) == [(0.0, WIDTH)]
    assert sector_rects(0, (), WIDTH) == []

"""The overlay renders the state the worker publishes, without a display."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from brake_trainer.config import Settings
from brake_trainer.models import SectorStatus, Snapshot, ViewState
from brake_trainer.ui import theme
from brake_trainer.ui.overlay import OverlayWindow

pytestmark = pytest.mark.usefixtures("close_qt_windows")


def _window(qapp, settings: Settings | None = None) -> OverlayWindow:
    return OverlayWindow(settings or Settings())


def _live(**over) -> ViewState:
    return ViewState(snapshot=Snapshot(track="Monza", car="Ferrari 296 GTB", **over), live=True)


def test_the_overlay_never_takes_focus_or_a_taskbar_slot(qapp):
    window = _window(qapp)

    flags = window.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_the_glyph_buttons_have_accessible_names(qapp):
    window = _window(qapp, Settings(learning_enabled=True))

    assert window._settings_btn.accessibleName() == "Settings"
    assert window._quit_btn.accessibleName() == "Quit"
    assert window._learn_btn.accessibleName() == "Pause learning"

    window.apply_settings(replace(window._settings, learning_enabled=False))
    assert window._learn_btn.accessibleName() == "Resume learning"


def test_the_default_position_is_on_the_primary_screen(qapp):
    from PySide6.QtGui import QGuiApplication

    window = _window(qapp)
    window.move_to_default()

    area = QGuiApplication.primaryScreen().availableGeometry()
    assert area.contains(window.pos())


def test_a_saved_position_inside_a_screen_is_restored(qapp):
    from PySide6.QtGui import QGuiApplication

    window = _window(qapp)
    area = QGuiApplication.primaryScreen().availableGeometry()

    window.place(area.x() + 10, area.y() + 10)

    assert (window.x(), window.y()) == (area.x() + 10, area.y() + 10)


def test_waiting_for_the_game_is_quiet(qapp):
    window = _window(qapp)

    window.update_state(ViewState(Snapshot()))

    assert window._title.text() == "Waiting for Assetto Corsa EVO…"
    assert window._distance.text() == "—"
    assert window._ref.isHidden()


def test_a_running_game_outside_a_session_says_so(qapp):
    window = _window(qapp)

    window.update_state(ViewState(Snapshot(), game_running=True))

    assert window._title.text() == "Game running — not in a session"
    assert theme.AMBER in window._dot.styleSheet()


def test_a_live_session_shows_the_track_car_distance_and_speed(qapp):
    window = _window(qapp)

    window.update_state(
        _live(
            speed_kmh=180.0,
            brake=0.4,
            braking=True,
            next_zone_m=150.0,
            lead_m=90.0,
            sector=1,
            sector_progress=0.2,
            sector_status=(SectorStatus.GOOD, SectorStatus.BEST, SectorStatus.PENDING),
            boundaries=(0.0, 0.3, 0.6, 1.0),
        )
    )

    assert window._title.text() == "Monza · Ferrari 296 GTB"
    assert window._distance.text() == "150 m"
    assert window._speed.text() == "180 km/h"
    assert window._approach._value == 0.625  # 400 m approach window
    assert window._sectors._status == (
        SectorStatus.GOOD,
        SectorStatus.BEST,
        SectorStatus.PENDING,
    )
    assert window._sectors._current == 1
    assert window._sectors._progress == 0.2
    assert window._sectors._boundaries == (0.0, 0.3, 0.6, 1.0)


def test_a_long_track_and_car_name_is_truncated(qapp):
    window = _window(qapp)
    state = ViewState(snapshot=Snapshot(track="A" * 40, car="B" * 20), live=True)

    window.update_state(state)

    assert window._title.text().endswith("…")
    assert len(window._title.text()) == 36


def test_showing_the_hover_buttons_does_not_move_the_title(qapp):
    window = _window(qapp)
    window.show()
    qapp.processEvents()
    window._set_buttons_visible(False)
    qapp.processEvents()
    window.update_state(_live())
    hidden = (window._dot.geometry(), window._title.geometry())

    window._set_buttons_visible(True)
    qapp.processEvents()
    window.update_state(_live())

    assert (window._dot.geometry(), window._title.geometry()) == hidden


def test_the_distance_row_keeps_one_height(qapp):
    window = _window(qapp)

    window.update_state(_live(warmup_laps_left=1))
    phase_height = window._distance.height()
    window.update_state(_live(next_zone_m=150.0, lead_m=90.0))
    number_height = window._distance.height()

    assert phase_height == number_height == 24


def test_warm_up_paused_and_no_points_have_their_own_words(qapp):
    warm = _window(qapp)
    warm.update_state(_live(warmup_laps_left=1))
    assert warm._distance.text() == "warm-up"
    assert warm._ref.text() == "Warm-up lap · not learning"

    paused = _window(qapp, Settings(learning_enabled=False))
    paused.update_state(_live())
    assert paused._distance.text() == "paused"
    assert paused._ref.text() == "Learning paused"

    empty = _window(qapp)
    empty.update_state(_live())
    assert empty._distance.text() == "learning…"
    assert empty._ref.text() == "No braking points yet"


def test_an_error_is_visible_even_without_samples(qapp):
    window = _window(qapp)

    window.update_state(ViewState(Snapshot(), live=False, error="Telemetry failed: no capture"))

    assert not window._ref.isHidden()
    assert window._ref.text() == "Telemetry failed: no capture"
    assert window._ref.toolTip() == "Telemetry failed: no capture"


def test_a_storage_warning_uses_the_status_line(qapp):
    window = _window(qapp)

    window.update_state(_live(storage_warning="Could not save learned data"))

    assert window._ref.text() == "Could not save learned data"
    assert theme.RED in window._ref.styleSheet()


def test_updating_settings_toggles_pause_and_window_flags(qapp):
    window = _window(qapp, Settings(learning_enabled=True, overlay_always_on_top=False))
    assert window._learn_btn.text() == "⏸"
    assert not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    window.apply_settings(
        replace(window._settings, learning_enabled=False, overlay_always_on_top=True)
    )

    assert window._learn_btn.text() == "▶"
    assert window._learn_btn.toolTip() == "Resume learning"
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_an_identical_state_does_not_rewrite_text_or_styles(qapp, monkeypatch):
    # The worker publishes about 20 times a second. Repainting an unchanged label or stylesheet
    # every frame is wasted work in the overlay, which sits over the game.
    window = _window(qapp)
    state = _live(next_zone_m=150.0, lead_m=90.0, speed_kmh=180.0)
    window.update_state(state)

    calls = {"style": 0, "text": 0}
    original_style = QLabel.setStyleSheet
    original_text = QLabel.setText

    def style(widget, css):
        calls["style"] += 1
        original_style(widget, css)

    def text(widget, value):
        calls["text"] += 1
        original_text(widget, value)

    monkeypatch.setattr(QLabel, "setStyleSheet", style)
    monkeypatch.setattr(QLabel, "setText", text)

    window.update_state(state)

    assert calls == {"style": 0, "text": 0}

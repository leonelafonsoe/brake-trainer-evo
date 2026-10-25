"""The settings dialog: form round-trip and the Data tab's delete requests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QLineEdit,
    QMessageBox,
    QSpinBox,
)

from brake_trainer.config import Settings
from brake_trainer.models import SectorRun, TrackData
from brake_trainer.settings_spec import TABS, SettingSpec
from brake_trainer.storage import DeleteEntry, DeleteRun, DeleteSector
from brake_trainer.ui import settings_window as settings_module
from brake_trainer.ui.settings_window import SettingsWindow, _get, _set

pytestmark = pytest.mark.usefixtures("close_qt_windows")


def _window(qapp, store, current: Settings | None = None) -> SettingsWindow:
    return SettingsWindow(lambda: current or Settings(), store)


def _stored(store) -> TrackData:
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05]), SectorRun(19.0, [])]
    data.sectors[1] = [SectorRun(20.0, [0.4])]
    data.boundaries = [0.3, 0.6]  # inner lines; the app adds 0.0 and 1.0 for display
    assert store.save(data)
    return data


def test_the_form_round_trips_every_visible_setting(qapp, store):
    window = _window(qapp, store)
    wanted = Settings(warmup_laps=3, learning_enabled=False, volume=0.4, overlay_opacity=0.8)

    window.load(wanted)

    assert window.collect() == wanted


def test_apply_shows_the_clamped_value_and_emits_it(qapp, store):
    window = _window(qapp, store)
    applied: list[Settings] = []
    window.applied.connect(applied.append)
    spec, widget = window._widgets["volume"]

    _set(widget, spec, 9.0)  # above the spin box's maximum
    window._apply()

    assert applied and applied[-1].volume == 1.0
    assert _get(widget, spec) == 1.0  # the form shows what will actually be used


def test_every_visible_setting_has_a_widget_of_the_right_kind(qapp, store):
    window = _window(qapp, store)
    visible = [spec for specs in TABS.values() for spec in specs]
    classes = {
        "bool": QCheckBox,
        "text": QLineEdit,
        "float": QDoubleSpinBox,
        "int": QSpinBox,
        "optint": QSpinBox,
    }

    assert set(window._widgets) == {spec.name for spec in visible}
    for spec in visible:
        assert isinstance(window._widgets[spec.name][1], classes[spec.kind]), spec.name
    assert "overlay_x" not in window._widgets
    assert "overlay_y" not in window._widgets


def _different_value(spec: SettingSpec):
    if spec.kind == "bool":
        return not spec.default
    if spec.kind == "text":
        return "different"
    assert spec.bounds is not None
    lo, hi = spec.bounds
    value = hi if spec.default != hi else lo
    return int(value) if spec.kind == "int" else float(value)


@pytest.mark.parametrize(
    "spec", [spec for specs in TABS.values() for spec in specs], ids=lambda spec: spec.name
)
def test_each_visible_setting_round_trips_through_the_form(qapp, store, spec):
    window = _window(qapp, store)
    wanted = replace(Settings(), **{spec.name: _different_value(spec)})

    window.load(wanted)

    assert window.collect() == wanted.clamped()


def test_collect_preserves_the_hidden_overlay_position(qapp, store):
    current = Settings(overlay_x=120, overlay_y=-5)
    window = _window(qapp, store, current)

    assert window.collect() == current


def test_the_data_tree_lists_entries_and_requests_deletes(qapp, store):
    _stored(store)
    window = _window(qapp, store)
    requested: list = []
    window.edit_requested.connect(requested.append)

    top = window._tree.topLevelItem(0)
    assert top is not None
    assert top.text(0) == "Monza · Car A"
    assert top.text(1) == "3 sectors · 3 runs"
    assert top.text(2) == "game's sector lines"

    sector = top.child(0)
    run = sector.child(0)
    assert sector.text(0) == "S1" and sector.childCount() == 2
    assert run.text(0) == "18.000 s" and run.text(1) == "1 braking point"

    window._tree.clearSelection()
    run.setSelected(True)
    assert window.selected_edits() == [DeleteRun("Monza", "Car A", 0, 18.0, (0.05,))]

    window._delete_selected()
    assert requested == [DeleteRun("Monza", "Car A", 0, 18.0, (0.05,))]


def test_selecting_a_parent_covers_its_children(qapp, store):
    _stored(store)
    window = _window(qapp, store)
    top = window._tree.topLevelItem(0)
    assert top is not None

    window._tree.clearSelection()
    top.child(0).setSelected(True)
    top.child(0).child(0).setSelected(True)
    assert window.selected_edits() == [DeleteSector("Monza", "Car A", 0)]


def test_deleting_a_whole_entry_asks_first(qapp, store, monkeypatch):
    _stored(store)
    window = _window(qapp, store)
    requested: list = []
    window.edit_requested.connect(requested.append)
    top = window._tree.topLevelItem(0)
    assert top is not None
    window._tree.clearSelection()
    top.setSelected(True)

    monkeypatch.setattr(
        settings_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    window._delete_selected()
    assert requested == []  # cancelled: nothing is deleted

    monkeypatch.setattr(
        settings_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._delete_selected()
    assert requested == [DeleteEntry("Monza", "Car A")]


def test_refreshing_keeps_an_expanded_entry_open(qapp, store):
    _stored(store)
    window = _window(qapp, store)
    top = window._tree.topLevelItem(0)
    assert top is not None

    top.setExpanded(True)
    window.refresh_data()

    refreshed = window._tree.topLevelItem(0)
    assert refreshed is not None and refreshed.isExpanded()


def test_without_a_selection_delete_does_nothing(qapp, store):
    _stored(store)
    window = _window(qapp, store)
    requested: list = []
    window.edit_requested.connect(requested.append)

    window._tree.clearSelection()
    window._delete_selected()

    assert requested == []

"""The settings/shutdown policy, tested without Qt, a game or a disk."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from brake_trainer.config import Settings, SettingsHolder
from brake_trainer.controller import AppController


class FakeWorker:
    def __init__(self, stop_ok: bool = True) -> None:
        self.settings: list[Settings] = []
        self.stop_requests = 0
        self.waits: list[int] = []
        self.terminated = 0
        self._stop_ok = stop_ok

    def update_settings(self, settings: Settings) -> None:
        self.settings.append(settings)

    def request_stop(self) -> None:
        self.stop_requests += 1

    def wait(self, msecs: int = -1) -> bool:
        self.waits.append(msecs)
        if len(self.waits) == 1:
            return self._stop_ok
        return True

    def terminate(self) -> None:
        self.terminated += 1


class FakeOverlay:
    def __init__(self) -> None:
        self.settings: list[Settings] = []

    def apply_settings(self, settings: Settings) -> None:
        self.settings.append(settings)


class FakeWindow:
    def __init__(self, visible: bool = False) -> None:
        self.visible = visible
        self.loaded: list[Settings] = []

    def isVisible(self) -> bool:
        return self.visible

    def load(self, settings: Settings) -> None:
        self.loaded.append(settings)


class FakeToggle:
    def __init__(self) -> None:
        self.checked: bool | None = None
        self.blocked: list[bool] = []

    def blockSignals(self, block: bool) -> bool:
        self.blocked.append(block)
        return False

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class FakeSave:
    """Save callback with scripted results (default: success)."""

    def __init__(self) -> None:
        self.calls: list[tuple[Settings, Path]] = []
        self.results: list[bool] = []

    def __call__(self, settings: Settings, path: Path) -> bool:
        self.calls.append((settings, path))
        return self.results.pop(0) if self.results else True


@pytest.fixture
def parts(tmp_path: Path):
    holder = SettingsHolder(Settings(volume=0.4))
    worker = FakeWorker()
    overlay = FakeOverlay()
    window = FakeWindow()
    toggles = {
        "learning_enabled": FakeToggle(),
        "overlay_always_on_top": FakeToggle(),
    }
    save = FakeSave()
    warnings: list[str] = []
    debug: list[bool] = []
    controller = AppController(
        holder=holder,
        worker=worker,
        overlay=overlay,
        window=window,
        toggles=toggles,
        save=save,
        settings_path=lambda: tmp_path / "settings.json",
        set_debug=debug.append,
        forced_debug=False,
        warn=warnings.append,
    )
    return SimpleNamespace(
        controller=controller,
        holder=holder,
        worker=worker,
        overlay=overlay,
        window=window,
        toggles=toggles,
        save=save,
        warnings=warnings,
        debug=debug,
        path=tmp_path / "settings.json",
    )


def test_apply_updates_every_consumer_and_saves(parts):
    wanted = replace(parts.holder.value, volume=0.9, learning_enabled=False, debug_logging=True)

    assert parts.controller.apply(wanted)

    assert parts.holder.value == wanted
    assert parts.save.calls == [(wanted, parts.path)]
    assert parts.worker.settings == [wanted]
    assert parts.overlay.settings == [wanted]
    assert parts.debug == [True]
    assert parts.toggles["learning_enabled"].checked is False
    assert parts.window.loaded == []  # hidden: no need to reload an invisible form


def test_apply_reloads_an_open_settings_window(parts):
    parts.window.visible = True
    wanted = replace(parts.holder.value, volume=0.1)

    parts.controller.apply(wanted)

    assert parts.window.loaded == [wanted]


def test_a_failed_save_warns_once_and_a_later_success_rearms_it(parts):
    parts.save.results = [False, False, True, False]

    assert not parts.controller.apply(Settings(volume=0.1))
    assert len(parts.warnings) == 1 and str(parts.path) in parts.warnings[0]

    assert not parts.controller.apply(Settings(volume=0.2))
    assert len(parts.warnings) == 1  # the same failure is not repeated on every toggle

    assert parts.controller.apply(Settings(volume=0.3))
    assert not parts.controller.apply(Settings(volume=0.4))
    assert len(parts.warnings) == 2  # a later failure is visible again


def test_a_failed_save_still_applies_for_the_session(parts):
    parts.save.results = [False]
    wanted = Settings(volume=0.7)

    parts.controller.apply(wanted)

    assert parts.holder.value == wanted
    assert parts.worker.settings == [wanted]
    assert parts.overlay.settings == [wanted]


def test_typed_setters_change_only_their_field(parts):
    parts.controller.set_learning(False)
    assert parts.holder.value.learning_enabled is False
    assert parts.holder.value.overlay_always_on_top is True

    parts.controller.set_always_on_top(False)
    assert parts.holder.value.overlay_always_on_top is False

    parts.controller.set_click_through(True)
    assert parts.holder.value.overlay_click_through is True

    parts.controller.move_overlay(120, -5)
    assert (parts.holder.value.overlay_x, parts.holder.value.overlay_y) == (120, -5)


def test_window_geometry_is_saved_without_reapplying(parts):
    parts.controller.save_window_geometry("Z2VvbWV0cnk=")

    assert parts.holder.value.window_geometry == "Z2VvbWV0cnk="
    assert parts.save.calls == [(parts.holder.value, parts.path)]
    assert parts.worker.settings == []  # geometry must not reapply the whole settings set

    parts.controller.save_window_geometry("Z2VvbWV0cnk=")
    assert len(parts.save.calls) == 1  # unchanged geometry is not written again


def test_shutdown_saves_stops_and_waits_once(parts):
    parts.controller.shutdown()

    assert parts.save.calls == [(parts.holder.value, parts.path)]
    assert parts.worker.stop_requests == 1
    assert parts.worker.waits == [5000]
    assert parts.worker.terminated == 0


def test_shutdown_terminates_a_worker_that_will_not_stop(tmp_path: Path, caplog):
    worker = FakeWorker(stop_ok=False)
    controller = AppController(
        holder=SettingsHolder(Settings()),
        worker=worker,
        overlay=FakeOverlay(),
        window=FakeWindow(),
        toggles={},
        save=FakeSave(),
        settings_path=lambda: tmp_path / "settings.json",
        set_debug=lambda _on: None,
        forced_debug=False,
        warn=lambda _text: None,
    )

    with caplog.at_level(logging.ERROR, logger="brake_trainer.controller"):
        controller.shutdown()

    assert worker.terminated == 1
    assert worker.waits == [5000, 1000]
    assert any("final data flush may be lost" in record.message for record in caplog.records)

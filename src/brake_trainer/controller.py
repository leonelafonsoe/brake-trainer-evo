"""Settings application and shutdown policy.

The Qt wiring in :mod:`brake_trainer.app` is deliberately thin: it builds the objects and connects
signals. What actually happens when settings are applied (save, warn, update the worker, overlay,
tray and open dialog) and when the app shuts down lives here, so it can be tested without a game,
a display or a real disk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .config import Settings, SettingsHolder

log = logging.getLogger(__name__)


class Toggle(Protocol):
    """The part of a checkable tray action the controller synchronises."""

    def blockSignals(self, block: bool) -> bool: ...

    def setChecked(self, checked: bool) -> None: ...


class Worker(Protocol):
    """The part of :class:`brake_trainer.ui.worker.EngineWorker` the controller uses."""

    def update_settings(self, settings: Settings) -> None: ...

    def request_stop(self) -> None: ...

    def wait(self, msecs: int = ...) -> bool: ...

    def terminate(self) -> None: ...


class Overlay(Protocol):
    def apply_settings(self, settings: Settings) -> None: ...


class Window(Protocol):
    def isVisible(self) -> bool: ...

    def load(self, settings: Settings) -> None: ...


class AppController:
    """Apply settings everywhere and shut the worker down exactly once."""

    def __init__(
        self,
        *,
        holder: SettingsHolder,
        worker: Worker,
        overlay: Overlay,
        window: Window,
        toggles: Mapping[str, Toggle],
        save: Callable[[Settings, Path], bool],
        settings_path: Callable[[], Path],
        set_debug: Callable[[bool], None],
        forced_debug: bool,
        warn: Callable[[str], None],
    ) -> None:
        self._holder = holder
        self._worker = worker
        self._overlay = overlay
        self._window = window
        self._toggles = toggles
        self._save = save
        self._settings_path = settings_path
        self._set_debug = set_debug
        self._forced_debug = forced_debug
        self._warn = warn
        self._save_warning_shown = False

    # ------------------------------------------------------------------ settings

    def apply(self, settings: Settings) -> bool:
        """Use ``settings`` for this session and save them. Returns whether the save succeeded."""
        self._holder.value = settings
        path = self._settings_path()
        saved = self._save(settings, path)
        if saved:
            self._save_warning_shown = False  # a later failure must be reported again
        elif not self._save_warning_shown:
            self._save_warning_shown = True
            log.error("Could not save settings to %s", path)
            self._warn(
                "The settings could not be written to:\n"
                f"{path}\n\n"
                "They apply for this session, but may be lost when the app exits. "
                "Check that the folder is writable."
            )
        self._worker.update_settings(settings)
        self._overlay.apply_settings(settings)
        self._set_debug(self._forced_debug or settings.debug_logging)
        for field, action in self._toggles.items():
            action.blockSignals(True)
            action.setChecked(getattr(settings, field))
            action.blockSignals(False)
        if self._window.isVisible():
            # A tray or overlay toggle while Settings is open must be reflected there, otherwise the
            # next Apply would write the stale form back and silently undo it.
            self._window.load(settings)
        return saved

    def set_learning(self, enabled: bool) -> None:
        self.apply(replace(self._holder.value, learning_enabled=enabled))

    def set_always_on_top(self, enabled: bool) -> None:
        self.apply(replace(self._holder.value, overlay_always_on_top=enabled))

    def set_click_through(self, enabled: bool) -> None:
        self.apply(replace(self._holder.value, overlay_click_through=enabled))

    def move_overlay(self, x: int, y: int) -> None:
        self.apply(replace(self._holder.value, overlay_x=x, overlay_y=y))

    def save_window_geometry(self, geometry: str) -> None:
        """Persist the settings dialog's geometry without re-applying settings anywhere else."""
        if not geometry or geometry == self._holder.value.window_geometry:
            return
        self._holder.value = replace(self._holder.value, window_geometry=geometry)
        path = self._settings_path()
        if not self._save(self._holder.value, path):
            log.error("Could not save settings to %s", path)

    # ------------------------------------------------------------------ lifecycle

    def shutdown(self) -> None:
        log.info("Shutting down")
        path = self._settings_path()
        if not self._save(self._holder.value, path):
            log.error("Could not save settings to %s", path)
        self._worker.request_stop()
        if not self._worker.wait(5000):
            # A live QThread must not be destroyed when main() returns. terminate() is a last
            # resort: it can skip the engine's final flush, so say so rather than hiding it.
            log.error(
                "Telemetry worker did not stop within 5 s; terminating it "
                "(its final data flush may be lost)"
            )
            self._worker.terminate()
            if not self._worker.wait(1000):
                log.error("Telemetry worker is still running after terminate(); exiting anyway")

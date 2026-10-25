"""Application entry point: wires the worker, the live overlay, the settings window and the tray."""

from __future__ import annotations

import contextlib
import logging
import sys
from dataclasses import replace
from typing import Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .audio import AudioPlayer
from .config import Settings, SettingsHolder, load_settings, save_settings
from .logsetup import configure_logging, debug_requested_on_startup, set_debug
from .paths import data_dir, settings_path
from .storage import TrackStore
from .ui import theme
from .ui.icon import app_icon
from .ui.overlay import OverlayWindow
from .ui.settings_window import SettingsWindow
from .ui.worker import EngineWorker

log = logging.getLogger("brake_trainer")

# Kept alive for the process lifetime; the installer's AppMutex checks this name.
_app_mutex: int | None = None


def _create_app_mutex() -> None:
    """Create the named mutex the installer checks before replacing a running program."""
    global _app_mutex
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        import ctypes

        _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "BrakeTrainerEvo.App")


def _set_taskbar_identity() -> None:
    """Give the process its own Windows taskbar identity, so the taskbar shows our icon (and not
    the Python interpreter's) when running from source."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BrakeTrainerEvo.App")


def main() -> int:
    forced_debug = debug_requested_on_startup(sys.argv)  # --debug / BRAKE_TRAINER_DEBUG
    configure_logging(debug=forced_debug)
    _create_app_mutex()
    _set_taskbar_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("Brake Trainer EVO")
    app.setStyleSheet(theme.STYLE)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # the overlay can be hidden; quit explicitly

    holder = SettingsHolder(load_settings(settings_path()))
    verbose = forced_debug or holder.value.debug_logging
    set_debug(verbose)
    if holder.value.debug_logging and not forced_debug:
        # The startup line already says debug=on when the flag or environment forced it.
        log.info("Verbose (debug) logging is on (setting)")
    store = TrackStore(data_dir())
    audio = AudioPlayer(lambda: holder.value)
    worker = EngineWorker(holder, store, audio)
    overlay = OverlayWindow(holder.value)
    settings_window = SettingsWindow(lambda: holder.value, store)

    toggles: dict[str, QAction] = {}  # tray checkboxes by settings field, kept in sync
    save_warning_shown = False

    def apply(settings: Settings) -> None:
        nonlocal save_warning_shown
        holder.value = settings
        if not save_settings(settings, settings_path()) and not save_warning_shown:
            # Applying still works for this session; make the risk visible instead of losing the
            # change silently at exit.
            save_warning_shown = True
            log.error("Could not save settings to %s", settings_path())
            QMessageBox.warning(
                settings_window,
                "Settings not saved",
                "The settings could not be written to:\n"
                f"{settings_path()}\n\n"
                "They apply for this session, but may be lost when the app exits. "
                "Check that the folder is writable.",
            )
        worker.update_settings(settings)
        overlay.apply_settings(settings)
        set_debug(forced_debug or settings.debug_logging)  # takes effect immediately
        for field, action in toggles.items():
            action.blockSignals(True)
            action.setChecked(getattr(settings, field))
            action.blockSignals(False)

    def update(**changes: Any) -> None:
        apply(replace(holder.value, **changes))

    def show_settings() -> None:
        settings_window.show()
        settings_window.raise_()
        settings_window.activateWindow()

    def show_overlay() -> None:
        overlay.show()
        overlay.raise_()

    # --- wiring
    worker.state.connect(overlay.update_state)
    worker.game_closed.connect(lambda: app.quit() if holder.value.close_with_game else None)
    overlay.settings_requested.connect(show_settings)
    overlay.quit_requested.connect(app.quit)
    overlay.toggle_on_top.connect(lambda on: update(overlay_always_on_top=on))
    overlay.toggle_learning.connect(lambda on: update(learning_enabled=on))
    overlay.moved.connect(lambda x, y: update(overlay_x=x, overlay_y=y))
    settings_window.applied.connect(apply)
    settings_window.edit_requested.connect(worker.request_edit)
    worker.data_changed.connect(settings_window.refresh_data)
    settings_window.test_cue.connect(lambda kind: audio.play(kind, force=True))

    # --- tray icon (a way back to the settings even when the overlay is click-through)
    tray = QSystemTrayIcon(app_icon(), app)
    tray.setToolTip("Brake Trainer EVO")
    menu = QMenu()
    menu.addAction("Settings…", show_settings)
    for field, text in (
        ("learning_enabled", "Learn braking points"),
        ("overlay_always_on_top", "Overlay always on top"),
        ("overlay_click_through", "Overlay click-through"),
    ):
        action = QAction(text, menu, checkable=True)
        action.setChecked(getattr(holder.value, field))
        action.toggled.connect(lambda on, f=field: update(**{f: on}))
        menu.addAction(action)
        toggles[field] = action
    menu.addAction("Show overlay", show_overlay)
    menu.addAction("Reset overlay position", overlay.reset_position)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    def shutdown() -> None:
        log.info("Shutting down")
        if not save_settings(holder.value, settings_path()):
            log.error("Could not save settings to %s", settings_path())
        worker.request_stop()
        if not worker.wait(5000):
            # A live QThread must not be destroyed when main() returns. terminate() is a last
            # resort: it can skip the engine's final flush, so say so rather than hiding it.
            log.error(
                "Telemetry worker did not stop within 5 s; terminating it "
                "(its final data flush may be lost)"
            )
            worker.terminate()
            if not worker.wait(1000):
                log.error("Telemetry worker is still running after terminate(); exiting anyway")

    app.aboutToQuit.connect(shutdown)

    overlay.place(holder.value.overlay_x, holder.value.overlay_y)
    overlay.show()
    worker.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

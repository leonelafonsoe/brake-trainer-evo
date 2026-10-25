"""Application entry point: wires the worker, the live overlay, the settings window and the tray."""

from __future__ import annotations

import contextlib
import logging
import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__
from .audio import AudioPlayer
from .config import SettingsHolder, load_settings, save_settings
from .controller import AppController
from .logsetup import configure_logging, debug_requested_on_startup, set_debug
from .paths import data_dir, settings_path
from .storage import TrackStore
from .ui import theme
from .ui.icon import app_icon
from .ui.overlay import OverlayWindow
from .ui.settings import SettingsWindow
from .ui.worker import EngineWorker

log = logging.getLogger("brake_trainer")

# Kept alive for the process lifetime; the installer's AppMutex checks this name.
_app_mutex: int | None = None


def _create_app_mutex() -> bool:
    """Create the installer's named mutex; return whether this is the first instance."""
    global _app_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _app_mutex = kernel32.CreateMutexW(None, False, "BrakeTrainerEvo.App")
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # pragma: no cover - ctypes failure must not stop the app
        return True


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
    if not _create_app_mutex():
        log.info("Brake Trainer EVO is already running; exiting")
        return 0
    _set_taskbar_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("Brake Trainer EVO")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # a consistent base for the dark QSS on Windows
    app.setPalette(theme.palette())
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
    settings_window = SettingsWindow(lambda: holder.value, store.directory)

    toggles: dict[str, QAction] = {}  # tray checkboxes by settings field, kept in sync

    def warn(message: str) -> None:
        QMessageBox.warning(settings_window, "Settings not saved", message)

    controller = AppController(
        holder=holder,
        worker=worker,
        overlay=overlay,
        window=settings_window,
        toggles=toggles,
        save=save_settings,
        settings_path=settings_path,
        set_debug=set_debug,
        forced_debug=forced_debug,
        warn=warn,
    )

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
    overlay.toggle_on_top.connect(controller.set_always_on_top)
    overlay.toggle_learning.connect(controller.set_learning)
    overlay.moved.connect(controller.move_overlay)
    settings_window.applied.connect(controller.apply)
    settings_window.edit_requested.connect(worker.request_edit)
    worker.data_snapshot.connect(settings_window.show_data_if_visible)
    settings_window.data_refresh_requested.connect(worker.request_data_refresh)
    settings_window.test_cue.connect(lambda kind: audio.play(kind, force=True))

    # --- tray icon (a way back to the settings even when the overlay is click-through)
    tray = QSystemTrayIcon(app_icon(), app)
    tray.setToolTip("Brake Trainer EVO")
    menu = QMenu()
    menu.addAction("Settings…", show_settings)
    for field, text, setter in (
        ("learning_enabled", "Learn braking points", controller.set_learning),
        ("overlay_always_on_top", "Overlay always on top", controller.set_always_on_top),
        ("overlay_click_through", "Overlay click-through", controller.set_click_through),
    ):
        action = QAction(text, menu, checkable=True)
        action.setChecked(getattr(holder.value, field))
        action.toggled.connect(lambda on, apply=setter: apply(on))
        menu.addAction(action)
        toggles[field] = action
    menu.addAction("Show overlay", show_overlay)
    menu.addAction("Reset overlay position", overlay.reset_position)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    app.aboutToQuit.connect(controller.shutdown)

    overlay.place(holder.value.overlay_x, holder.value.overlay_y)
    overlay.show()
    worker.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

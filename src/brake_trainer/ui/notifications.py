"""Non-modal notifications for problems that must not steal focus mid-drive."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon, QWidget

_TRAY_TIMEOUT_MS = 8000


def warn(tray: QSystemTrayIcon | None, parent: QWidget | None, title: str, message: str) -> None:
    """Show a tray balloon when possible, otherwise fall back to a modal dialog.

    A settings-save failure can come from a tray toggle or an overlay drag while the game is
    running. A modal dialog would take keyboard focus away from the game, so the tray message is
    preferred whenever it is supported and visible.
    """
    if tray is not None and tray.isVisible() and QSystemTrayIcon.supportsMessages():
        tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, _TRAY_TIMEOUT_MS)
        return
    QMessageBox.warning(parent, title, message)

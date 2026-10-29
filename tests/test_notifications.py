"""Save-failure warnings should not take focus from the game."""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

from brake_trainer.ui import notifications

pytestmark = pytest.mark.usefixtures("close_qt_windows")


class FakeTray:
    def __init__(self, visible: bool = True) -> None:
        self.visible = visible
        self.messages: list[tuple[str, str, QSystemTrayIcon.MessageIcon, int]] = []

    def isVisible(self) -> bool:
        return self.visible

    def showMessage(
        self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon, timeout: int
    ) -> None:
        self.messages.append((title, message, icon, timeout))


def test_a_visible_tray_gets_a_non_modal_message(qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", lambda: True)
    tray = FakeTray()
    dialogs: list[tuple[object, ...]] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: dialogs.append(args))

    notifications.warn(cast(QSystemTrayIcon, tray), None, "Settings not saved", "the disk is full")

    assert tray.messages == [
        (
            "Settings not saved",
            "the disk is full",
            QSystemTrayIcon.MessageIcon.Warning,
            8000,
        )
    ]
    assert dialogs == []


def test_a_hidden_or_unsupported_tray_falls_back_to_a_dialog(qapp, monkeypatch):
    dialogs: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: dialogs.append((parent, title, message)),
    )

    notifications.warn(
        cast(QSystemTrayIcon, FakeTray(visible=False)), None, "Settings not saved", "hidden tray"
    )
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", lambda: False)
    notifications.warn(
        cast(QSystemTrayIcon, FakeTray()), None, "Settings not saved", "no balloon support"
    )

    assert dialogs == [
        (None, "Settings not saved", "hidden tray"),
        (None, "Settings not saved", "no balloon support"),
    ]

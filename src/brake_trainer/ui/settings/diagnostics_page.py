"""Diagnostics tab: logging options and shortcuts to the folders worth sharing."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...gamelog import DEFAULT_LOG_DIR
from ...paths import app_dir
from ...settings_spec import SettingSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...config import Settings


class DiagnosticsPageMixin:
    if TYPE_CHECKING:
        # Provided by SettingsWindow and the sibling mixins.
        _get_settings: Callable[[], Settings]

        def _form(self, specs: list[SettingSpec]) -> QWidget: ...

        def _open_folder(self) -> None: ...

    def _diagnostics_tab(self, specs: list[SettingSpec]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        intro = QLabel(
            "Troubleshooting. Verbose logging adds detail about the game's track-limit signals "
            "(every cut read from the game's log, with the sector it is attributed to, and the lap "
            "flag). Turn it on, reproduce the problem, then share the app log: the fastest way to "
            "explain a sector that was kept or dropped wrongly."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self._form(specs))
        row = QHBoxLayout()
        for text, slot in (
            ("Open app log folder", self._open_log_folder),
            ("Open the game's log folder", self._open_game_log_folder),
            ("Open data folder", self._open_folder),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _open_log_folder(self) -> None:
        self._reveal(app_dir())

    def _open_game_log_folder(self) -> None:
        folder = self._get_settings().game_log_dir
        self._reveal(Path(folder).expanduser() if folder else DEFAULT_LOG_DIR)

    @staticmethod
    def _reveal(folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

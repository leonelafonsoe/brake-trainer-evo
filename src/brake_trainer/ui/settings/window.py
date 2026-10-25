"""Settings window: every tunable, grouped in tabs, plus management of the learned data."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import Settings
from ...models import CueKind
from ...settings_spec import TABS, SettingSpec
from .about_page import AboutPageMixin
from .data_page import DataPageMixin
from .diagnostics_page import DiagnosticsPageMixin
from .form import FormMixin


class SettingsWindow(FormMixin, DiagnosticsPageMixin, DataPageMixin, AboutPageMixin, QDialog):
    applied = Signal(object)  # Settings
    test_cue = Signal(object)  # CueKind
    edit_requested = Signal(object)  # DataEdit
    data_refresh_requested = Signal()
    geometry_changed = Signal(str)

    _get_settings: Callable[[], Settings]
    _data_dir: Path
    _widgets: dict[str, tuple[SettingSpec, QWidget]]
    _tabs: QTabWidget
    _tree: QTreeWidget

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        data_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_settings = get_settings
        self._data_dir = data_dir
        self._widgets: dict[str, tuple[SettingSpec, QWidget]] = {}
        self.setWindowTitle("Brake Trainer — Settings")
        self.setMinimumWidth(560)
        saved_geometry = get_settings().window_geometry
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromBase64(saved_geometry.encode("ascii")))

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        for title, specs in TABS.items():
            page = self._diagnostics_tab(specs) if title == "Diagnostics" else self._form(specs)
            self._tabs.addTab(page, title)
        self._tabs.addTab(self._data_tab(), "Data")
        self._tabs.addTab(self._about_tab(), "About")
        layout.addWidget(self._tabs)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.setObjectName("reset")
        reset.setAutoDefault(False)
        reset.clicked.connect(lambda: self.load(Settings()))
        warn, here = QPushButton("Test warning"), QPushButton("Test brake-now")
        warn.setAutoDefault(False)
        here.setAutoDefault(False)
        warn.clicked.connect(lambda: self.test_cue.emit(CueKind.WARN))
        here.clicked.connect(lambda: self.test_cue.emit(CueKind.HERE))
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("apply")
        apply_btn.setProperty("primary", True)
        # Enter applies. Without this Qt would make the first button in tab order (Reset) default,
        # so pressing Enter in a field could throw the form away.
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        for b in (reset, warn, here):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.load(get_settings())

    def showEvent(self, event: Any) -> None:  # noqa: N802
        self.load(self._get_settings())
        self.data_refresh_requested.emit()
        super().showEvent(event)

    def save_geometry(self) -> None:
        """Remember the dialog's position and size, so it reopens there next time."""
        self.geometry_changed.emit(bytes(self.saveGeometry().toBase64().data()).decode("ascii"))

    def _is_dirty(self) -> bool:
        return self.collect() != self._get_settings().clamped()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.isVisible() and self._is_dirty():
            answer = QMessageBox.question(
                self,
                "Discard changes?",
                "You have unapplied settings. Close without applying them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.save_geometry()
        super().closeEvent(event)

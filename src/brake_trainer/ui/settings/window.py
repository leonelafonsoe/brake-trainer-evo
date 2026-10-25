"""Settings window: every tunable, grouped in tabs, plus management of the learned data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import Settings
from ...models import CueKind
from ...settings_spec import TABS, SettingSpec
from ...storage import TrackStore
from .about_page import AboutPageMixin
from .data_page import DataPageMixin
from .diagnostics_page import DiagnosticsPageMixin
from .form import FormMixin


class SettingsWindow(FormMixin, DiagnosticsPageMixin, DataPageMixin, AboutPageMixin, QDialog):
    applied = Signal(object)  # Settings
    test_cue = Signal(object)  # CueKind
    edit_requested = Signal(object)  # DataEdit

    _get_settings: Callable[[], Settings]
    _store: TrackStore
    _widgets: dict[str, tuple[SettingSpec, QWidget]]
    _tabs: QTabWidget
    _tree: QTreeWidget

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        store: TrackStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_settings = get_settings
        self._store = store
        self._widgets: dict[str, tuple[SettingSpec, QWidget]] = {}
        self.setWindowTitle("Brake Trainer — Settings")
        self.setMinimumWidth(560)

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
        self.refresh_data()
        super().showEvent(event)

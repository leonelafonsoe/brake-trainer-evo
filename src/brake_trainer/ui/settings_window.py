"""Settings window: every tunable, grouped in tabs, plus management of the learned data."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import Settings
from ..gamelog import DEFAULT_LOG_DIR
from ..models import CueKind
from ..paths import app_dir
from ..settings_spec import TABS, SettingSpec
from ..storage import DataEdit, DeleteEntry, DeleteRun, DeleteSector, TrackStore
from . import theme

_ABOUT_HTML = (
    "<style>a {{ color: #4da3ff; }}</style>"
    "<h3>Brake Trainer EVO {version}</h3>"
    "<p>Learns where you brake on each track and car, and beeps as you approach those points.</p>"
    "<p><b>Credits</b><br>"
    "&bull; <a href='https://github.com/glebulon/acevo-sdk'>acevo-sdk</a> by Gleb Zverinskiy, "
    "which reads the game's telemetry. Without it this would not be possible.<br>"
    "&bull; <a href='https://www.overtake.gg/downloads/brake-trainer.32511/'>Brake Trainer</a> "
    "by AugGust, the original app for Assetto Corsa that inspired this project.</p>"
    "<p><b>Vibe coded.</b> Written almost entirely by an AI assistant (Claude) together with the "
    "maintainer. Expect rough edges and please report bugs.</p>"
    "<p>License: PolyForm Noncommercial 1.0.0. Free to use, share and modify for "
    "non-commercial purposes; not for sale.</p>"
)


_EDIT_ROLE = Qt.ItemDataRole.UserRole


def _make_widget(spec: SettingSpec) -> QWidget:
    w: QWidget
    if spec.kind == "bool":
        w = QCheckBox()
    elif spec.kind == "text":
        w = QLineEdit()
    elif spec.kind == "float":
        assert spec.lo is not None and spec.hi is not None
        w = QDoubleSpinBox()
        w.setDecimals(spec.decimals)
        w.setRange(spec.lo, spec.hi)
        w.setSingleStep(spec.step)
        w.setSuffix(spec.suffix)
    else:
        assert spec.lo is not None and spec.hi is not None
        w = QSpinBox()
        w.setRange(int(spec.lo), int(spec.hi))
        w.setSingleStep(int(spec.step))
        w.setSuffix(spec.suffix)
        if spec.kind == "optint":
            w.setSpecialValueText("Auto")
        elif spec.special:
            w.setSpecialValueText(spec.special)
    if spec.tip:
        w.setToolTip(spec.tip)
    return w


def _set(widget: QWidget, spec: SettingSpec, value: Any) -> None:
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value or 0))


def _get(widget: QWidget, spec: SettingSpec) -> Any:
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    if isinstance(widget, QDoubleSpinBox):
        return widget.value()
    assert isinstance(widget, QSpinBox)
    value = widget.value()
    return (value or None) if spec.kind == "optint" else value


class SettingsWindow(QDialog):
    applied = Signal(object)  # Settings
    test_cue = Signal(object)  # CueKind
    edit_requested = Signal(object)  # DataEdit

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
        reset.clicked.connect(lambda: self.load(Settings()))
        warn, here = QPushButton("Test warning"), QPushButton("Test brake-now")
        warn.clicked.connect(lambda: self.test_cue.emit(CueKind.WARN))
        here.clicked.connect(lambda: self.test_cue.emit(CueKind.HERE))
        apply_btn = QPushButton("Apply")
        apply_btn.setProperty("primary", True)
        apply_btn.clicked.connect(self._apply)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        for b in (reset, warn, here):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.load(get_settings())

    # ------------------------------------------------------------------ building

    def _form(self, specs: list[SettingSpec]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(10)
        for spec in specs:
            widget = _make_widget(spec)
            self._widgets[spec.name] = (spec, widget)
            form.addRow(spec.label, widget)
        return page

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

    def _data_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Learned braking data. Expand a track and car to see its sectors and the runs kept for "
            "each, and delete just the one you do not trust."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Track / car / sector / run", "Details", "Sector lines"])
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setRootIsDecorated(True)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._tree)
        row = QHBoxLayout()
        for text, slot in (
            ("Refresh", self.refresh_data),
            ("Delete selected", self._delete_selected),
            ("Open data folder", self._open_folder),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh_data()
        return page

    def _about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        label = QLabel(_ABOUT_HTML.format(version=__version__))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(theme.ACCENT))
        label.setPalette(palette)
        layout.addWidget(label)
        return page

    # ------------------------------------------------------------------ values

    def load(self, settings: Settings) -> None:
        for name, (spec, widget) in self._widgets.items():
            _set(widget, spec, getattr(settings, name))

    def collect(self) -> Settings:
        values = {name: _get(widget, spec) for name, (spec, widget) in self._widgets.items()}
        return replace(self._get_settings(), **values).clamped()

    def _apply(self) -> None:
        settings = self.collect()
        self.load(settings)  # show clamped values
        self.applied.emit(settings)

    # ------------------------------------------------------------------ data tab

    def refresh_data(self) -> None:
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is not None and top.isExpanded():
                expanded.add(top.data(0, _EDIT_ROLE))
        self._tree.clear()
        for d in self._store.entries():
            lines = "game's sector lines" if d.boundaries else "equal splits"
            total = d.total_runs()
            detail = f"{d.n_sectors} sectors · {total} run" + ("" if total == 1 else "s")
            entry = QTreeWidgetItem([f"{d.track} · {d.car}", detail, lines])
            entry_edit = DeleteEntry(d.track, d.car)
            entry.setData(0, _EDIT_ROLE, entry_edit)
            for index, runs in enumerate(d.sectors):
                best = f"best {runs[0].t:.3f} s · " if runs else ""
                count = f"{len(runs)} run" + ("" if len(runs) == 1 else "s")
                sector = QTreeWidgetItem([f"S{index + 1}", f"{best}{count}"])
                sector.setData(0, _EDIT_ROLE, DeleteSector(d.track, d.car, index))
                for run in runs:
                    points = len(run.onsets)
                    label = "braking point" if points == 1 else "braking points"
                    item = QTreeWidgetItem([f"{run.t:.3f} s", f"{points} {label}"])
                    item.setData(
                        0, _EDIT_ROLE, DeleteRun(d.track, d.car, index, run.t, tuple(run.onsets))
                    )
                    sector.addChild(item)
                entry.addChild(sector)
            self._tree.addTopLevelItem(entry)
            entry.setExpanded(entry_edit in expanded)
        issues = self._store.issues()
        if issues:
            group = QTreeWidgetItem([f"Unavailable files ({len(issues)})", "", ""])
            group.setDisabled(True)
            for issue in issues:
                outcome = (
                    f"moved to {issue.quarantine_path.name}"
                    if issue.quarantine_path is not None
                    else "read-only — not overwritten"
                )
                item = QTreeWidgetItem(
                    [f"⚠ {issue.path.stem}", f"{issue.status.value}: {issue.detail}", outcome]
                )
                item.setDisabled(True)
                item.setToolTip(0, str(issue.path))
                if issue.quarantine_path is not None:
                    item.setToolTip(2, str(issue.quarantine_path))
                group.addChild(item)
            self._tree.addTopLevelItem(group)
            group.setExpanded(True)

    def selected_edits(self) -> list[DataEdit]:
        """The edits for the selected rows. A selected entry covers its sectors and runs."""
        items = self._tree.selectedItems()
        chosen = {id(i) for i in items}
        edits: list[DataEdit] = []
        for item in items:
            parent, covered = item.parent(), False
            while parent is not None:
                covered = covered or id(parent) in chosen
                parent = parent.parent()
            if not covered:
                edit = item.data(0, _EDIT_ROLE)
                if edit is not None:
                    edits.append(edit)
        return edits

    def _delete_selected(self) -> None:
        edits = self.selected_edits()
        if not edits:
            return
        whole = [e for e in edits if isinstance(e, DeleteEntry)]
        if whole:
            names = ", ".join(f"{e.track} / {e.car}" for e in whole)
            answer = QMessageBox.question(
                self,
                "Delete data",
                f"Delete everything learned for {names}? This cannot be undone.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        for edit in edits:
            self.edit_requested.emit(edit)  # applied by the worker, then the tab refreshes

    def _open_folder(self) -> None:
        self._reveal(self._store.directory)

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

    def showEvent(self, event: Any) -> None:  # noqa: N802
        self.load(self._get_settings())
        self.refresh_data()
        super().showEvent(event)


__all__ = ["TABS", "SettingSpec", "SettingsWindow", "Qt"]

"""Data tab: browse the learned entries and request deletes."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...storage import DataEdit, DataSnapshot, DeleteEntry, DeleteRun, DeleteSector

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtCore import SignalInstance


_EDIT_ROLE = Qt.ItemDataRole.UserRole


class DataPageMixin:
    if TYPE_CHECKING:
        # Provided by SettingsWindow and the diagnostics mixin.
        _tree: QTreeWidget
        _data_dir: Path
        edit_requested: SignalInstance
        data_refresh_requested: SignalInstance

        def _reveal(self, folder: Path) -> None: ...
        def isVisible(self) -> bool: ...

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
            ("Refresh", self.request_data),
            ("Delete selected", self._delete_selected),
            ("Open data folder", self._open_folder),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        # No scan here: the window refreshes when it is shown. Reading the data folder while the
        # app starts would delay the overlay and could quarantine a file without the driver ever
        # opening Settings.
        return page

    def request_data(self) -> None:
        """Ask the worker for a fresh snapshot; it owns the store and does the disk read."""
        self.data_refresh_requested.emit()

    def show_data_if_visible(self, snapshot: DataSnapshot) -> None:
        """Render a snapshot published by the worker, but never while the window is hidden."""
        if self.isVisible():
            self.render_data(snapshot)

    def render_data(self, snapshot: DataSnapshot) -> None:
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is not None and top.isExpanded():
                expanded.add(top.data(0, _EDIT_ROLE))
        self._tree.clear()
        for d in snapshot.entries:
            lines = "game's sector lines" if d.game_lines else "equal splits"
            total = d.total_runs()
            detail = f"{d.n_sectors} sectors · {total} run" + ("" if total == 1 else "s")
            entry = QTreeWidgetItem([f"{d.track} · {d.car}", detail, lines])
            entry_edit = DeleteEntry(d.track, d.car)
            entry.setData(0, _EDIT_ROLE, entry_edit)
            for index, runs in enumerate(d.sectors):
                best = f"best {runs[0].time:.3f} s · " if runs else ""
                count = f"{len(runs)} run" + ("" if len(runs) == 1 else "s")
                sector = QTreeWidgetItem([f"S{index + 1}", f"{best}{count}"])
                sector.setData(0, _EDIT_ROLE, DeleteSector(d.track, d.car, index))
                for run in runs:
                    points = len(run.onsets)
                    label = "braking point" if points == 1 else "braking points"
                    item = QTreeWidgetItem([f"{run.time:.3f} s", f"{points} {label}"])
                    item.setData(
                        0, _EDIT_ROLE, DeleteRun(d.track, d.car, index, run.time, run.onsets)
                    )
                    sector.addChild(item)
                entry.addChild(sector)
            self._tree.addTopLevelItem(entry)
            entry.setExpanded(entry_edit in expanded)
        issues = snapshot.issues
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
                cast(QWidget, self),
                "Delete data",
                f"Delete everything learned for {names}? This cannot be undone.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        for edit in edits:
            self.edit_requested.emit(edit)  # applied by the worker, then the tab refreshes

    def _open_folder(self) -> None:
        self._reveal(self._data_dir)

"""Settings window: every tunable, grouped in tabs, plus management of the learned data."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
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


@dataclass(frozen=True)
class Spec:
    name: str
    label: str
    kind: str  # float | int | optint | bool | text
    lo: float = 0.0
    hi: float = 0.0
    step: float = 1.0
    decimals: int = 2
    suffix: str = ""
    tip: str = ""
    special: str = ""  # text shown for the minimum value (e.g. "Off")


TABS: dict[str, list[Spec]] = {
    "Cues": [
        Spec(
            "sound_enabled",
            "Sound cues",
            "bool",
            tip="Turn all cue sounds on or off. The overlay keeps working.",
        ),
        Spec(
            "volume",
            "Volume",
            "float",
            0,
            1,
            0.05,
            2,
            tip="Loudness of the beeps, from 0 (silent) to 1.",
        ),
        Spec(
            "lead_s",
            "Warning lead time",
            "float",
            0.3,
            5,
            0.1,
            1,
            " s",
            "The low beep sounds this many seconds before the braking point.",
        ),
        Spec(
            "min_lead_m",
            "Minimum warning distance",
            "float",
            5,
            300,
            5,
            0,
            " m",
            "At low speed the warning never comes closer than this.",
        ),
        Spec(
            "here_m",
            "'Brake now' window",
            "float",
            2,
            50,
            1,
            0,
            " m",
            "The high beep sounds when you are this close to the point.",
        ),
        Spec(
            "skip_zone_if_braking",
            "Skip cue if brake above",
            "float",
            0,
            1,
            0.05,
            2,
            tip="No beep if you are already braking harder than this.",
        ),
        Spec(
            "warn_hz",
            "Warning tone",
            "int",
            200,
            4000,
            50,
            suffix=" Hz",
            tip="Pitch of the low warning beep (braking point coming up).",
        ),
        Spec(
            "warn_ms",
            "Warning length",
            "int",
            30,
            500,
            10,
            suffix=" ms",
            tip="Length of the warning beep.",
        ),
        Spec(
            "here_hz",
            "Brake-now tone",
            "int",
            200,
            4000,
            50,
            suffix=" Hz",
            tip="Pitch of the high beep (you are at the braking point).",
        ),
        Spec(
            "here_ms",
            "Brake-now length",
            "int",
            30,
            500,
            10,
            suffix=" ms",
            tip="Length of the high beep.",
        ),
    ],
    "Detection": [
        Spec(
            "brake_on",
            "Braking starts above",
            "float",
            0.05,
            0.95,
            0.05,
            2,
            tip="Pedal position that counts as the start of a braking event.",
        ),
        Spec(
            "brake_off",
            "Braking ends below",
            "float",
            0.01,
            0.9,
            0.01,
            2,
            tip="Pedal position below which a braking event ends.",
        ),
        Spec(
            "min_peak",
            "Minimum peak pressure",
            "float",
            0.1,
            1,
            0.05,
            2,
            tip="Light brake touches below this peak are ignored.",
        ),
        Spec(
            "min_speed_drop",
            "Minimum speed shed",
            "float",
            1,
            100,
            1,
            0,
            " km/h",
            tip="A braking event must slow the car by at least this much.",
        ),
        Spec(
            "cluster_m",
            "Same-corner distance",
            "float",
            5,
            200,
            5,
            0,
            " m",
            tip="Braking starts closer than this are treated as the same corner.",
        ),
    ],
    "Sectors": [
        Spec(
            "learning_enabled",
            "Learn braking points",
            "bool",
            tip="Off = cues still play, but nothing is saved or changed (e.g. during a race).",
        ),
        Spec(
            "warmup_laps",
            "Ignore laps after leaving the pits",
            "int",
            0,
            5,
            1,
            special="Off",
            tip=(
                "Cold tyres and brakes make you brake earlier, so these laps are not learned. "
                "The first laps of a new track are ignored too, while the game's sector lines are "
                "being learned from its log."
            ),
        ),
        Spec(
            "skip_invalid_sectors",
            "Skip sector if lap invalidated",
            "bool",
            tip="A sector where the game invalidates your lap (track limits, cuts) is not saved.",
        ),
        Spec(
            "max_tyres_out",
            "Skip sector if tyres off track",
            "int",
            0,
            4,
            1,
            special="Off",
            tip=(
                "The game's live count of tyres off the track, where it publishes it. A sector is "
                "not saved if this many were off at any moment, also twice in the same lap. Off "
                "leaves it to the game's race cut and the lap flag."
            ),
        ),
        Spec(
            "max_tyres_out_after_invalid",
            "...once the lap is invalid",
            "int",
            0,
            4,
            1,
            special="Off",
            tip=(
                "The game's lap flag only drops once, so the race cut and the tyre count carry the "
                "later mistakes. For the rest of an invalidated lap a sector is not saved if this "
                "many tyres go off the track in it."
            ),
        ),
        Spec(
            "top_runs",
            "Fastest runs kept per sector",
            "int",
            1,
            10,
            1,
            tip="Cue points are the median of these runs. 1 = copy your single best run.",
        ),
        Spec(
            "own_runs_to_replace_ref",
            "Own runs before leaving reference",
            "int",
            1,
            10,
            1,
            tip="With a new car, borrowed points are used until you have this many runs.",
        ),
        Spec(
            "reference_car",
            "Preferred reference car",
            "text",
            tip="Part of a car name. Empty = the car with the most data on that track.",
        ),
    ],
    "Overlay": [
        Spec(
            "overlay_always_on_top",
            "Always on top",
            "bool",
            tip="Needs the game in borderless / windowed mode to be visible over it.",
        ),
        Spec(
            "overlay_opacity",
            "Opacity",
            "float",
            0.3,
            1,
            0.05,
            2,
            tip="Opacity of the whole overlay, text included.",
        ),
        Spec(
            "overlay_background",
            "Background opacity",
            "float",
            0,
            0.9,
            0.05,
            2,
            tip="0 = fully transparent (HUD style). Raise it if the text is hard to read.",
        ),
        Spec(
            "overlay_click_through",
            "Click-through",
            "bool",
            tip="Mouse clicks pass through to the game. Use the tray icon to switch it off.",
        ),
    ],
    "App": [
        Spec(
            "close_with_game",
            "Close when the game exits",
            "bool",
            tip="Quit automatically (after saving) when the game exits.",
        ),
        Spec(
            "game_process",
            "Game process name contains",
            "text",
            tip="Part of the game's process name, used to detect that it is running or has closed.",
        ),
        Spec(
            "use_game_log",
            "Follow the game's log",
            "bool",
            tip=(
                "Read the game's log for the cuts it reports and the sector splits that mark its "
                'own lines. Shared memory only shows the first cut of a lap (its "lap valid" flag '
                "drops once); the log records one event per cut and every sector split."
            ),
        ),
        Spec(
            "game_log_dir",
            "Game log folder",
            "text",
            tip=(
                "Where the game writes its logs. Empty = the usual place under Saved Games "
                "(<profile>/Saved Games/ACE/Logs)."
            ),
        ),
        Spec(
            "telemetry_hz",
            "Telemetry rate",
            "float",
            5,
            60,
            5,
            0,
            " Hz",
            tip=(
                "How often telemetry is read. Higher makes live data a little smoother; 60 is "
                "plenty. Sector lines are interpolated between samples rather than snapped to "
                "them, so a higher rate only refines the estimate."
            ),
        ),
    ],
    "Diagnostics": [
        Spec(
            "debug_logging",
            "Verbose (debug) logging",
            "bool",
            tip=(
                "Write extra detail to the log, including the game's track-limit signals (the race "
                "cut and the live tyre count) and the lap flag at every change. Turn it on, "
                "reproduce a problem, then share the log file."
            ),
        ),
    ],
}


def _make_widget(spec: Spec) -> QWidget:
    w: QWidget
    if spec.kind == "bool":
        w = QCheckBox()
    elif spec.kind == "text":
        w = QLineEdit()
    elif spec.kind == "float":
        w = QDoubleSpinBox()
        w.setDecimals(spec.decimals)
        w.setRange(spec.lo, spec.hi)
        w.setSingleStep(spec.step)
        w.setSuffix(spec.suffix)
    else:
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


def _set(widget: QWidget, spec: Spec, value: Any) -> None:
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value or 0))


def _get(widget: QWidget, spec: Spec) -> Any:
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
        self._widgets: dict[str, tuple[Spec, QWidget]] = {}
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

    def _form(self, specs: list[Spec]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(10)
        for spec in specs:
            widget = _make_widget(spec)
            self._widgets[spec.name] = (spec, widget)
            form.addRow(spec.label, widget)
        return page

    def _diagnostics_tab(self, specs: list[Spec]) -> QWidget:
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
                    item.setData(0, _EDIT_ROLE, DeleteRun(d.track, d.car, index, run.t))
                    sector.addChild(item)
                entry.addChild(sector)
            self._tree.addTopLevelItem(entry)
            entry.setExpanded(entry_edit in expanded)

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
                edits.append(item.data(0, _EDIT_ROLE))
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


__all__ = ["TABS", "SettingsWindow", "Spec", "Qt"]

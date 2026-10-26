"""Build the settings form and move values between widgets and ``Settings``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from ...config import Settings
from ...hotkey import HotkeyError, parse_hotkey
from ...settings_spec import SettingSpec

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance


def _make_widget(spec: SettingSpec) -> QWidget:
    w: QWidget
    if spec.kind == "bool":
        w = QCheckBox()
    elif spec.kind == "hotkey":
        edit = QKeySequenceEdit()
        edit.setMaximumSequenceLength(1)  # one chord: the app registers a single hotkey
        edit.setClearButtonEnabled(True)  # the clear button is how "off" is set
        w = edit
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


def _qt_sequence(text: str) -> QKeySequence:
    """Qt calls the Windows key ``Meta``; the settings text and the docs call it ``Win``."""
    return QKeySequence("+".join("Meta" if part == "Win" else part for part in text.split("+")))


def _set(widget: QWidget, spec: SettingSpec, value: Any) -> None:
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QKeySequenceEdit):
        if value:
            widget.setKeySequence(_qt_sequence(str(value)))
        else:
            widget.clear()
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value or 0))


def _get(widget: QWidget, spec: SettingSpec) -> Any:
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QKeySequenceEdit):
        sequence = widget.keySequence()
        if sequence.isEmpty():
            return ""
        text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        try:
            hotkey = parse_hotkey(text)
        except HotkeyError:
            return text  # Apply shows the parse error instead of silently turning the key off
        return hotkey.text if hotkey is not None else ""
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    if isinstance(widget, QDoubleSpinBox):
        return widget.value()
    assert isinstance(widget, QSpinBox)
    value = widget.value()
    return (value or None) if spec.kind == "optint" else value


class FormMixin:
    if TYPE_CHECKING:
        # Provided by SettingsWindow; declared here so the mixin can be checked on its own.
        _widgets: dict[str, tuple[SettingSpec, QWidget]]
        _get_settings: Callable[[], Settings]
        applied: SignalInstance

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

    def load(self, settings: Settings) -> None:
        for name, (spec, widget) in self._widgets.items():
            _set(widget, spec, getattr(settings, name))

    def collect(self) -> Settings:
        values = {name: _get(widget, spec) for name, (spec, widget) in self._widgets.items()}
        return replace(self._get_settings(), **values).clamped()

    def _apply(self) -> None:
        settings = self.collect()
        problem = settings.validation_error()
        if problem:
            QMessageBox.warning(cast(QWidget, self), "Check the settings", problem)
            return
        self.load(settings)  # show clamped values
        self.applied.emit(settings)

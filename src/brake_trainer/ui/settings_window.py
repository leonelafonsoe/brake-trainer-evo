"""Compatibility shim: the settings window now lives in :mod:`brake_trainer.ui.settings`."""

from __future__ import annotations

from PySide6.QtCore import Qt

from .settings import TABS, SettingSpec, SettingsWindow, _get, _set

__all__ = ["TABS", "SettingSpec", "SettingsWindow", "Qt", "_get", "_set"]

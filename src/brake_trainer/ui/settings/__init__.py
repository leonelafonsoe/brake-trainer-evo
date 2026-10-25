"""Settings window package: form, diagnostics, data and about pages."""

from __future__ import annotations

from ...settings_spec import TABS, SettingSpec
from .form import _get, _set
from .window import SettingsWindow

__all__ = ["TABS", "SettingSpec", "SettingsWindow", "_get", "_set"]

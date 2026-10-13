from __future__ import annotations

import importlib.util
from dataclasses import fields
from pathlib import Path

from brake_trainer.config import Settings
from brake_trainer.ui.settings_window import TABS

ROOT = Path(__file__).resolve().parent.parent


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_settings_doc", ROOT / "scripts" / "gen_settings_doc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_reference_is_up_to_date():
    expected = _generator().render()
    current = (ROOT / "docs" / "SETTINGS.md").read_text(encoding="utf-8")
    assert current == expected, "run: py scripts/gen_settings_doc.py"


def test_every_settings_window_field_exists_in_settings():
    names = {f.name for f in fields(Settings)}
    shown = {spec.name for specs in TABS.values() for spec in specs}
    assert shown <= names

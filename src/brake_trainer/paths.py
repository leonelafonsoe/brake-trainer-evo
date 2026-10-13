"""Where the app keeps its files (settings, learned data, logs)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "BrakeTrainerEvo"
HOME_ENV = "BRAKE_TRAINER_HOME"  # override, mainly for tests


def app_dir() -> Path:
    """Per-user app folder (``%APPDATA%\\BrakeTrainerEvo`` on Windows), created on demand."""
    override = os.environ.get(HOME_ENV)
    if override:
        root = Path(override)
    else:
        appdata = os.environ.get("APPDATA") if sys.platform == "win32" else None
        root = (Path(appdata) if appdata else Path.home() / ".config") / APP_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = Path(tempfile.gettempdir()) / APP_NAME
        root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir() -> Path:
    path = app_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_dir() / "settings.json"


def log_path() -> Path:
    return app_dir() / "brake_trainer.log"

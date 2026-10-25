"""Build metadata stamped into the files the app writes.

The app version, the build identifier and the save time are informational: they make a settings
file or a learned-data file easy to match to a build when one is shared for support. The loaders
ignore these keys, so a file from an older or newer build still reads as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import __version__
from .buildinfo import build_id


def save_metadata() -> dict[str, Any]:
    """The fields written at the top of every file the app saves."""
    return {
        "app_version": __version__,
        "build": build_id(),
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

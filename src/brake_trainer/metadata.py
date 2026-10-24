"""Build metadata stamped into the files the app writes.

The app version and the save time are informational: they make a settings file, a learned-data
file or a log easy to match to a build when one is shared for support. The loaders ignore these
keys, so a file from an older or newer build still reads as before.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import __version__


def save_metadata() -> dict[str, Any]:
    """The fields written at the top of every file the app saves."""
    return {
        "app_version": __version__,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

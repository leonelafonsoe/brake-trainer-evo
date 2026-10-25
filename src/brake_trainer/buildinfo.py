"""Identify the code that is running, for the startup log and the files the app saves.

The app version alone cannot tell two builds apart while a fix is being tested: the same
``0.4.0`` can be a released executable, a checkout before the fix, or a checkout with the fix and
uncommitted edits. A build identifier closes that gap. It is provenance only - nothing reads it to
decide whether a file is compatible. See ``docs/GAME_DATA.md``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

BUILD_ENV = "BRAKE_TRAINER_BUILD"  # set to name a build explicitly (packagers, tests, local runs)
BUILD_FILE = "build-id.txt"  # baked into a frozen build by scripts/build_exe.py
UNKNOWN = "unknown"
PACKAGED = "packaged"

# src/brake_trainer/buildinfo.py -> the checkout root
_ROOT = Path(__file__).resolve().parents[2]


def build_id() -> str:
    """A short identifier for the running build, in order of preference:

    1. ``BRAKE_TRAINER_BUILD``, so a build can be named explicitly;
    2. the identifier a frozen build baked in at build time;
    3. the git revision of a source checkout (``-dirty`` when it has uncommitted changes);
    4. ``packaged`` inside a frozen executable with no baked identifier;
    5. ``unknown`` if there is no checkout and no override.

    Best effort: a missing ``git`` or an unreadable checkout must never stop the app from starting.
    """
    override = os.environ.get(BUILD_ENV, "").strip()
    if override:
        return override
    if getattr(sys, "frozen", False):
        return _embedded_build_id() or PACKAGED
    return _git_describe() or UNKNOWN


def _embedded_build_id() -> str:
    """The identifier written into a frozen build, or "" when there is none."""
    base = Path(getattr(sys, "_MEIPASS", _ROOT))
    try:
        return (base / BUILD_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@lru_cache(maxsize=1)
def _git_describe() -> str:
    """The checkout's commit (and ``-dirty``), or "" when this is not a checkout."""
    if not (_ROOT / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(_ROOT), "describe", "--always", "--dirty", "--abbrev=12"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
            # A windowed app must not flash a console window while asking git.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()

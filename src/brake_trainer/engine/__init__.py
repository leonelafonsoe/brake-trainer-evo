"""Braking-point learning engine.

The public surface is the engine and the small value helpers other layers use. Private test hooks
are imported from the module that owns them, not re-exported here.
"""

from __future__ import annotations

from .constants import DEFAULT_LENGTH_M, N_SECTORS
from .engine import BrakeEngine
from .limits import build_zones, merge_zones, race_cut_active
from .lines import full_bounds

__all__ = [
    "DEFAULT_LENGTH_M",
    "N_SECTORS",
    "BrakeEngine",
    "build_zones",
    "full_bounds",
    "merge_zones",
    "race_cut_active",
]

"""Braking-point learning engine.

This package keeps the public import path ``brake_trainer.engine``. Only the re-exports below
are public: the modules behind them may be reorganised, the names here may not.
"""

from __future__ import annotations

from .constants import _HISTORY_S, DEFAULT_LENGTH_M, N_SECTORS
from .cues import _BrakeEvent
from .engine import BrakeEngine
from .limits import build_zones, merge_zones, race_cut_active
from .lines import _split_position_ok, full_bounds
from .passes import _LapRun, _LostPass, _Pass

__all__ = [
    "DEFAULT_LENGTH_M",
    "N_SECTORS",
    "BrakeEngine",
    "build_zones",
    "full_bounds",
    "merge_zones",
    "race_cut_active",
    "_BrakeEvent",
    "_HISTORY_S",
    "_LapRun",
    "_LostPass",
    "_Pass",
    "_split_position_ok",
]

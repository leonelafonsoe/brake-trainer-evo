"""User settings: a frozen dataclass, validated on load, stored as JSON."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# (min, max) per numeric field; values outside are clamped on load / apply.
_LIMITS: dict[str, tuple[float, float]] = {
    "brake_on": (0.05, 0.95),
    "brake_off": (0.01, 0.9),
    "min_peak": (0.1, 1.0),
    "min_speed_drop": (1.0, 100.0),
    "cluster_m": (5.0, 200.0),
    "top_runs": (1, 10),
    "max_tyres_out": (0, 4),
    "max_tyres_out_after_invalid": (0, 4),
    "cut_give_back_m": (0.0, 2000.0),
    "warmup_laps": (0, 5),
    "own_runs_to_replace_ref": (1, 10),
    "lead_s": (0.3, 5.0),
    "min_lead_m": (5.0, 300.0),
    "here_m": (2.0, 50.0),
    "skip_zone_if_braking": (0.0, 1.0),
    "warn_hz": (200, 4000),
    "here_hz": (200, 4000),
    "warn_ms": (30, 500),
    "here_ms": (30, 500),
    "volume": (0.0, 1.0),
    "telemetry_hz": (5.0, 60.0),
    "overlay_opacity": (0.3, 1.0),
    "overlay_background": (0.0, 0.9),
}
_OPTIONAL_INT = {"overlay_x", "overlay_y"}


@dataclass(frozen=True, slots=True)
class Settings:
    # --- braking detection ---
    brake_on: float = 0.25  # brake above this = braking started
    brake_off: float = 0.10  # brake below this = braking ended
    min_peak: float = 0.40  # ignore light touches below this peak
    min_speed_drop: float = 15.0  # km/h that must be shed for an event to count
    cluster_m: float = 40.0  # onsets closer than this are the same corner
    # --- sectors & learning ---
    learning_enabled: bool = True  # off: cues still play, nothing is saved or changed
    top_runs: int = 3  # fastest runs kept per sector
    warmup_laps: int = 1  # laps ignored after leaving the pits (cold tyres and brakes)
    skip_invalid_sectors: bool = True  # sector not counted if the lap was invalidated in it
    max_tyres_out: int = 4  # tyres off the track that drop a sector (0 = ignore)
    # Once the game has invalidated the lap its flag stays down and cannot report a second mistake,
    # so a lower tyre count stands in for it in the remaining sectors of that lap (0 = off).
    max_tyres_out_after_invalid: int = 2
    # The game judges a cut and only reports it after its give-back window has passed. Its report
    # names the corner it happened in, so the position it arrives at is used as-is (0 = trust it).
    # A non-zero window reads the report this far back along the lap for old data that expects it.
    cut_give_back_m: float = 0.0
    own_runs_to_replace_ref: int = 2
    reference_car: str = ""  # "" = automatic
    # --- cues ---
    lead_s: float = 1.6
    min_lead_m: float = 35.0
    here_m: float = 8.0
    skip_zone_if_braking: float = 0.10
    sound_enabled: bool = True
    volume: float = 0.6
    warn_hz: int = 900
    here_hz: int = 1800
    warn_ms: int = 90
    here_ms: int = 120
    # --- app ---
    telemetry_hz: float = 60.0
    game_process: str = "assettocorsaevo"
    close_with_game: bool = True
    use_game_log: bool = True  # follow the game's log for the cuts it reports after the fact
    game_log_dir: str = ""  # "" = the game's default folder under Saved Games
    debug_logging: bool = False  # verbose log for troubleshooting (see docs/TROUBLESHOOTING.md)
    # --- overlay ---
    overlay_always_on_top: bool = True
    overlay_opacity: float = 1.0
    overlay_background: float = 0.0  # 0 = fully transparent, HUD style
    overlay_click_through: bool = False
    overlay_x: int | None = None
    overlay_y: int | None = None

    def clamped(self) -> Settings:
        changes: dict[str, Any] = {}
        for name, (lo, hi) in _LIMITS.items():
            value = getattr(self, name)
            if value is None:
                continue
            fixed = min(max(value, lo), hi)
            if isinstance(value, int) and not isinstance(value, bool):
                fixed = int(fixed)
            if fixed != value:
                changes[name] = fixed
        merged = replace(self, **changes)
        if merged.brake_off >= merged.brake_on:
            merged = replace(merged, brake_off=max(0.01, merged.brake_on - 0.05))
        return merged

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Settings:
        """Build from untrusted data: unknown keys and wrong types fall back to defaults."""
        defaults = cls()
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            value, default = raw[f.name], getattr(defaults, f.name)
            if f.name in _OPTIONAL_INT:
                if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                    values[f.name] = value
            elif isinstance(default, bool):
                if isinstance(value, bool):
                    values[f.name] = value
            elif isinstance(default, int):
                if isinstance(value, int) and not isinstance(value, bool):
                    values[f.name] = value
            elif isinstance(default, float):
                if isinstance(value, int | float) and not isinstance(value, bool):
                    values[f.name] = float(value)
            elif isinstance(default, str) and isinstance(value, str):
                values[f.name] = value
        return cls(**values).clamped()

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


class SettingsHolder:
    """Mutable reference to the current settings, shared between threads."""

    def __init__(self, value: Settings) -> None:
        self.value = value


def load_settings(path: Path) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return Settings.from_dict(raw)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("Could not read settings (%s); using defaults", exc)
    return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Could not save settings: %s", exc)

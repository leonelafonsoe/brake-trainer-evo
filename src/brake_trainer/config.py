"""User settings: a frozen dataclass, validated on load, stored as JSON."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from .metadata import save_metadata

log = logging.getLogger(__name__)

# Bumped when a stored setting needs to change meaning; see Settings.from_dict.
SETTINGS_VERSION = 3

# Stamped into every file; the loader ignores them, so they are never carried over from an old file.
_METADATA_KEYS = frozenset({"app_version", "build", "saved_at"})

# (min, max) per numeric field; values outside are clamped on load / apply.
_LIMITS: dict[str, tuple[float, float]] = {
    "brake_on": (0.05, 0.95),
    "brake_off": (0.01, 0.9),
    "min_peak": (0.1, 1.0),
    "min_speed_drop": (1.0, 100.0),
    "cluster_m": (5.0, 200.0),
    "top_runs": (1, 10),
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
    settings_version: int = SETTINGS_VERSION  # stored so an old file is migrated only once

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
        """Build from untrusted data: unknown keys and wrong types fall back to defaults.

        Retired settings are simply unknown keys now, so a file that still stores one
        (``cut_give_back_m`` from version 2) loads without it and is written back in the current
        shape.

        A file from a *newer* build is not migrated: its version is left alone and a warning is
        logged. This build cannot know what changed after its own version, and writing the version
        down would make the next build migrate the file a second time. Saving from here keeps that
        version and the keys this build does not know, so the newer build still finds its choices
        (see :func:`save_settings`).
        """
        defaults = cls()
        values: dict[str, Any] = {}
        try:
            raw_version = int(raw.get("settings_version", 1))
        except (TypeError, ValueError):
            raw_version = 1
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
        settings = cls(**values).clamped()
        if raw_version > SETTINGS_VERSION:
            log.warning(
                "Settings file is from a newer version (%d > %d); leaving its version alone",
                raw_version,
                SETTINGS_VERSION,
            )
            return replace(settings, settings_version=raw_version)
        if raw_version < SETTINGS_VERSION:
            return replace(settings, settings_version=SETTINGS_VERSION)
        return settings

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


def _preserved_settings(path: Path) -> tuple[dict[str, Any], int]:
    """Unknown keys and version from an existing file, when it is from a newer build.

    Retired keys from an older/equal file are deliberately not preserved: they are migration
    leftovers, not settings this build does not understand. A newer file's unknown keys are kept so
    that saving from an older build does not delete choices the newer build made.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, 0
    if not isinstance(raw, dict):
        return {}, 0
    try:
        version = int(raw.get("settings_version", 0))
    except (TypeError, ValueError):
        version = 0
    if version <= SETTINGS_VERSION:
        return {}, version
    known = {f.name for f in fields(Settings)} | _METADATA_KEYS
    extras = {key: value for key, value in raw.items() if key not in known}
    return extras, version


def save_settings(settings: Settings, path: Path) -> bool:
    """Write settings, keeping unknown keys from a newer file. Returns False on a failed write."""
    tmp = path.with_suffix(".tmp")
    extras, stored_version = _preserved_settings(path)
    payload = {
        **save_metadata(),
        **extras,
        **settings.to_dict(),
        "settings_version": max(settings.settings_version, stored_version),
    }
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Could not save settings: %s", exc)
        return False
    return True

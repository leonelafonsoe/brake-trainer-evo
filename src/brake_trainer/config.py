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
from .settings_spec import DEFAULTS, SPEC_BY_NAME
from .settings_spec import LIMITS as _LIMITS
from .settings_spec import SETTINGS_VERSION as SETTINGS_VERSION

log = logging.getLogger(__name__)

# Stamped into every file; the loader ignores them, so they are never carried over from an old file.
_METADATA_KEYS = frozenset({"app_version", "build", "saved_at"})


@dataclass(frozen=True, slots=True)
class Settings:
    # --- braking detection ---
    brake_on: float = DEFAULTS["brake_on"]  # brake above this = braking started
    brake_off: float = DEFAULTS["brake_off"]  # brake below this = braking ended
    min_peak: float = DEFAULTS["min_peak"]  # ignore light touches below this peak
    # km/h that must be shed for an event to count
    min_speed_drop: float = DEFAULTS["min_speed_drop"]
    cluster_m: float = DEFAULTS["cluster_m"]  # onsets closer than this are the same corner
    # --- sectors & learning ---
    # off: cues still play, nothing is saved or changed
    learning_enabled: bool = DEFAULTS["learning_enabled"]
    top_runs: int = DEFAULTS["top_runs"]  # fastest runs kept per sector
    # laps ignored after leaving the pits (cold tyres and brakes)
    warmup_laps: int = DEFAULTS["warmup_laps"]
    # sector not counted if the lap was invalidated in it
    skip_invalid_sectors: bool = DEFAULTS["skip_invalid_sectors"]
    own_runs_to_replace_ref: int = DEFAULTS["own_runs_to_replace_ref"]
    reference_car: str = DEFAULTS["reference_car"]  # "" = automatic
    # --- cues ---
    lead_s: float = DEFAULTS["lead_s"]
    min_lead_m: float = DEFAULTS["min_lead_m"]
    here_m: float = DEFAULTS["here_m"]
    skip_zone_if_braking: float = DEFAULTS["skip_zone_if_braking"]
    sound_enabled: bool = DEFAULTS["sound_enabled"]
    volume: float = DEFAULTS["volume"]
    warn_hz: int = DEFAULTS["warn_hz"]
    here_hz: int = DEFAULTS["here_hz"]
    warn_ms: int = DEFAULTS["warn_ms"]
    here_ms: int = DEFAULTS["here_ms"]
    # --- app ---
    telemetry_hz: float = DEFAULTS["telemetry_hz"]
    game_process: str = DEFAULTS["game_process"]
    close_with_game: bool = DEFAULTS["close_with_game"]
    # follow the game's log for the cuts it reports after the fact
    use_game_log: bool = DEFAULTS["use_game_log"]
    # "" = the game's default folder under Saved Games
    game_log_dir: str = DEFAULTS["game_log_dir"]
    # verbose log for troubleshooting (see docs/TROUBLESHOOTING.md)
    debug_logging: bool = DEFAULTS["debug_logging"]
    # --- overlay ---
    overlay_always_on_top: bool = DEFAULTS["overlay_always_on_top"]
    overlay_opacity: float = DEFAULTS["overlay_opacity"]
    overlay_background: float = DEFAULTS["overlay_background"]  # 0 = fully transparent, HUD style
    overlay_click_through: bool = DEFAULTS["overlay_click_through"]
    overlay_x: int | None = DEFAULTS["overlay_x"]
    overlay_y: int | None = DEFAULTS["overlay_y"]
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
        values: dict[str, Any] = {}
        try:
            raw_version = int(raw.get("settings_version", 1))
        except (TypeError, ValueError):
            raw_version = 1
        for f in fields(cls):
            if f.name not in raw:
                continue
            spec = SPEC_BY_NAME.get(f.name)
            if spec is None:  # the registry tests forbid this; be defensive for old files
                continue
            value = raw[f.name]
            if spec.kind == "optint":
                if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                    values[f.name] = value
            elif spec.kind == "bool":
                if isinstance(value, bool):
                    values[f.name] = value
            elif spec.kind == "int":
                if isinstance(value, int) and not isinstance(value, bool):
                    values[f.name] = value
            elif spec.kind == "float":
                if isinstance(value, int | float) and not isinstance(value, bool):
                    values[f.name] = float(value)
            elif spec.kind == "text" and isinstance(value, str):
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

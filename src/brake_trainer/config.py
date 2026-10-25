"""User settings: a frozen dataclass, validated on load, stored as JSON."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .metadata import save_metadata
from .settings_spec import DEFAULTS, SPEC_BY_NAME
from .settings_spec import LIMITS as _LIMITS
from .settings_spec import SETTINGS_VERSION as SETTINGS_VERSION

log = logging.getLogger(__name__)

# Settings files this process could not read or move aside. Saving over one would destroy evidence
# and the user's choices, so writes are refused for the rest of the run (as learned data is).
_unreadable_settings: set[Path] = set()


@dataclass(frozen=True, slots=True)
class Settings:
    # --- braking detection ---
    brake_on: float = DEFAULTS["brake_on"]  # brake above this = braking started
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
    reference_car: str = DEFAULTS["reference_car"]  # "" = automatic
    # --- cues ---
    lead_s: float = DEFAULTS["lead_s"]
    here_m: float = DEFAULTS["here_m"]
    skip_zone_if_braking: float = DEFAULTS["skip_zone_if_braking"]
    volume: float = DEFAULTS["volume"]
    warn_hz: int = DEFAULTS["warn_hz"]
    here_hz: int = DEFAULTS["here_hz"]
    # --- app ---
    telemetry_hz: float = DEFAULTS["telemetry_hz"]
    game_process: str = DEFAULTS["game_process"]
    close_with_game: bool = DEFAULTS["close_with_game"]
    # follow the game's log for the cuts it reports after the fact
    use_game_log: bool = DEFAULTS["use_game_log"]
    # "" = the game's default folder under Saved Games
    game_log_dir: str = DEFAULTS["game_log_dir"]
    # verbose log for troubleshooting (see docs/GUIDE.md#logs-and-resetting)
    debug_logging: bool = DEFAULTS["debug_logging"]
    # --- overlay ---
    overlay_always_on_top: bool = DEFAULTS["overlay_always_on_top"]
    overlay_opacity: float = DEFAULTS["overlay_opacity"]
    overlay_background: float = DEFAULTS["overlay_background"]  # 0 = fully transparent, HUD style
    overlay_click_through: bool = DEFAULTS["overlay_click_through"]
    overlay_x: int | None = DEFAULTS["overlay_x"]
    overlay_y: int | None = DEFAULTS["overlay_y"]

    def clamped(self) -> Settings:
        changes: dict[str, Any] = {}
        for name, (lo, hi) in _LIMITS.items():
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, float) and not math.isfinite(value):
                changes[name] = DEFAULTS[name]  # NaN/Inf cannot be clamped into a usable value
                continue
            fixed = min(max(value, lo), hi)
            if isinstance(value, int) and not isinstance(value, bool):
                fixed = int(fixed)
            if fixed != value:
                changes[name] = fixed
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Settings:
        """Build from untrusted data: unknown keys and wrong types fall back to defaults.

        The caller has already checked ``settings_version``; a file from another version is
        archived instead of being partly loaded (see :func:`load_settings`).
        """
        values: dict[str, Any] = {}
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
                    number = float(value)
                    if math.isfinite(number):
                        values[f.name] = number
            elif spec.kind == "text" and isinstance(value, str):
                values[f.name] = value
        return cls(**values).clamped()

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


class SettingsHolder:
    """Mutable reference to the current settings, shared between threads."""

    def __init__(self, value: Settings) -> None:
        self.value = value


def _archive_settings(path: Path, reason: str) -> bool:
    """Move a settings file this build cannot use aside; False when it could not be moved."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.{reason}-{stamp}{path.suffix}")
    counter = 1
    while target.exists():
        target = path.with_name(f"{path.stem}.{reason}-{stamp}-{counter}{path.suffix}")
        counter += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        log.error("Could not move settings %s aside: %s", path, exc)
        return False
    log.warning(
        "Settings %s could not be used; moved to %s and starting from defaults", path, target
    )
    return True


def load_settings(path: Path) -> Settings:
    """Read settings, starting from defaults if the file cannot be used.

    An unreadable file is moved aside, never overwritten. If it cannot be moved, saves are refused
    for the rest of the run so the user's file and the evidence in it survive.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except OSError as exc:
        log.error("Could not read settings %s: %s; writes are disabled", path, exc)
        _unreadable_settings.add(path)
        return Settings()
    try:
        raw = json.loads(text)
    except ValueError as exc:
        log.warning("Settings file is not valid JSON: %s", exc)
        raw = None
    if not isinstance(raw, dict):
        if not _archive_settings(path, "invalid"):
            _unreadable_settings.add(path)
        return Settings()
    try:
        version = int(raw.get("settings_version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != SETTINGS_VERSION:
        # No migrations: a file from another layout is kept as evidence and the app starts clean.
        if not _archive_settings(path, f"version-{version}"):
            _unreadable_settings.add(path)
        return Settings()
    return Settings.from_dict(raw)


def save_settings(settings: Settings, path: Path) -> bool:
    """Write settings atomically. Returns False on a failed write."""
    if path in _unreadable_settings:
        log.error("Refusing to overwrite unreadable settings %s", path)
        return False
    tmp = path.with_suffix(".tmp")
    payload = {**save_metadata(), **settings.to_dict(), "settings_version": SETTINGS_VERSION}
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2))
            handle.flush()
            os.fsync(handle.fileno())  # durable before the replace, not just in the cache
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        log.warning("Could not save settings: %s", exc)
        return False
    return True

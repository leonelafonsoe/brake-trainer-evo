"""The single source of truth for settings metadata.

This module is pure: it must not import Qt, the config loader or the UI. The dataclass defaults,
the clamping bounds, the form labels/tips and the generated settings reference all derive from
``SPECS``. Adding a setting means adding one :class:`SettingSpec` here and the matching typed field
to :class:`brake_trainer.config.Settings`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from .hotkey import DEFAULT_PAUSE_HOTKEY

Kind = Literal["bool", "int", "optint", "float", "text", "hotkey"]

# Bumped when the stored settings layout changes. A file with any other version is archived and the
# app starts from defaults (see config.load_settings): there is no migration code to keep.
# 5: renamed the internal JSON keys (old files are archived; user tuning is not migrated).
SETTINGS_VERSION = 5

TAB_ORDER: tuple[str, ...] = (
    "Cues",
    "Detection",
    "Sectors",
    "Overlay",
    "App",
    "Diagnostics",
    "Advanced",
)


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """What one setting is called, where it is shown and how it is validated.

    ``default`` is typed ``Any`` because the registry is heterogeneous. The real type contract is
    the matching field annotation on ``Settings``; the registry tests check that the two agree.
    """

    name: str
    kind: Kind
    default: Any
    tab: str | None = None  # None = stored but not shown in the window
    label: str = ""
    lo: float | None = None
    hi: float | None = None
    step: float = 1.0
    decimals: int = 2
    suffix: str = ""
    tip: str = ""
    special: str = ""  # text shown for the minimum value, e.g. "Off"

    @property
    def visible(self) -> bool:
        return self.tab is not None

    @property
    def bounds(self) -> tuple[float, float] | None:
        if self.lo is None or self.hi is None:
            return None
        return self.lo, self.hi

    def coerce(self, value: object) -> object:
        """Validate one JSON value for this setting, raising when it is not the right kind.

        Bounds are applied later by ``Settings.clamped()``; this only decides whether the value can
        be used at all. ``bool`` is rejected as a number, floats must be finite, and the optional
        integer fields accept ``None``.
        """
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
        elif self.kind == "int":
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        elif self.kind == "optint":
            if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                return value
        elif self.kind == "float":
            if isinstance(value, int | float) and not isinstance(value, bool):
                number = float(value)
                if math.isfinite(number):
                    return number
        elif self.kind in {"text", "hotkey"} and isinstance(value, str):
            return value
        raise TypeError(f"{self.name} is not a valid {self.kind}: {value!r}")


SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        name="volume",
        kind="float",
        default=0.6,
        tab="Cues",
        label="Volume",
        lo=0.0,
        hi=1.0,
        step=0.05,
        tip="Loudness of the beeps, from 0 (silent) to 1.",
    ),
    SettingSpec(
        name="warn_lead_s",
        kind="float",
        default=1.6,
        tab="Cues",
        label="Warning lead time",
        lo=0.3,
        hi=5.0,
        step=0.1,
        decimals=1,
        suffix=" s",
        tip="The low beep sounds this many seconds before the braking point.",
    ),
    SettingSpec(
        name="brake_now_m",
        kind="float",
        default=8.0,
        tab="Cues",
        label="'Brake now' window",
        lo=2.0,
        hi=50.0,
        decimals=0,
        suffix=" m",
        tip="The high beep sounds when you are this close to the point.",
    ),
    SettingSpec(
        name="skip_zone_if_braking",
        kind="float",
        default=0.1,
        tab="Advanced",
        label="Skip cue if brake above",
        lo=0.0,
        hi=1.0,
        step=0.05,
        tip="No beep if you are already braking harder than this.",
    ),
    SettingSpec(
        name="warn_hz",
        kind="int",
        default=900,
        tab="Cues",
        label="Warning tone",
        lo=200,
        hi=4000,
        step=50,
        suffix=" Hz",
        tip="Pitch of the low warning beep (braking point coming up).",
    ),
    SettingSpec(
        name="brake_now_hz",
        kind="int",
        default=1800,
        tab="Cues",
        label="Brake-now tone",
        lo=200,
        hi=4000,
        step=50,
        suffix=" Hz",
        tip="Pitch of the high beep (you are at the braking point).",
    ),
    SettingSpec(
        name="brake_threshold",
        kind="float",
        default=0.25,
        tab="Detection",
        label="Braking starts above",
        lo=0.05,
        hi=0.95,
        step=0.05,
        tip="Pedal position that counts as the start of a braking event.",
    ),
    SettingSpec(
        name="min_peak",
        kind="float",
        default=0.4,
        tab="Advanced",
        label="Minimum peak pressure",
        lo=0.1,
        hi=1.0,
        step=0.05,
        tip="Light brake touches below this peak are ignored.",
    ),
    SettingSpec(
        name="min_speed_shed",
        kind="float",
        default=15.0,
        tab="Detection",
        label="Minimum speed shed",
        lo=1.0,
        hi=100.0,
        decimals=0,
        suffix=" km/h",
        tip="A braking event must slow the car by at least this much.",
    ),
    SettingSpec(
        name="same_corner_m",
        kind="float",
        default=40.0,
        tab="Advanced",
        label="Same-corner distance",
        lo=5.0,
        hi=200.0,
        step=5,
        decimals=0,
        suffix=" m",
        tip="Braking starts closer than this are treated as the same corner.",
    ),
    SettingSpec(
        name="learning_enabled",
        kind="bool",
        default=True,
        tab="Sectors",
        label="Learn braking points",
        tip=(
            "Off = cues still play, but no braking points or sector times are saved or changed"
            " (e.g. during a race)."
        ),
    ),
    SettingSpec(
        name="warmup_laps",
        kind="int",
        default=1,
        tab="Sectors",
        label="Ignore laps after leaving the pits",
        lo=0,
        hi=5,
        tip=(
            "Cold tyres and brakes make you brake earlier, so these laps are not learned. The first"
            " laps of a new track are ignored too, while the game's sector lines are being learned"
            " from its log."
        ),
        special="Off",
    ),
    SettingSpec(
        name="kept_runs",
        kind="int",
        default=3,
        tab="Sectors",
        label="Fastest runs kept per sector",
        lo=1,
        hi=10,
        tip="Cue points are the median of these runs. 1 = copy your single best run.",
    ),
    SettingSpec(
        name="reference_car",
        kind="text",
        default="",
        tab="Sectors",
        label="Preferred reference car",
        tip="Part of a car name. Empty = the car with the most data on that track.",
    ),
    SettingSpec(
        name="hud_scale",
        kind="float",
        default=1.0,
        tab="Overlay",
        label="HUD scale",
        lo=0.75,
        hi=2.0,
        step=0.05,
        decimals=2,
        suffix="×",
        tip=(
            "Scale the overlay text and layout. 1.00 is the normal size; use 1.25-1.50 on a"
            " high-DPI screen."
        ),
    ),
    SettingSpec(
        name="overlay_always_on_top",
        kind="bool",
        default=True,
        tab="Overlay",
        label="Always on top",
        tip="Needs the game in borderless / windowed mode to be visible over it.",
    ),
    SettingSpec(
        name="overlay_opacity",
        kind="float",
        default=1.0,
        tab="Overlay",
        label="Opacity",
        lo=0.3,
        hi=1.0,
        step=0.05,
        tip="Opacity of the whole overlay, text included.",
    ),
    SettingSpec(
        name="overlay_background",
        kind="float",
        default=0.0,
        tab="Overlay",
        label="Background opacity",
        lo=0.0,
        hi=0.9,
        step=0.05,
        tip="0 = fully transparent (HUD style). Raise it if the text is hard to read.",
    ),
    SettingSpec(
        name="overlay_click_through",
        kind="bool",
        default=False,
        tab="Overlay",
        label="Click-through",
        tip="Mouse clicks pass through to the game. Use the tray icon to switch it off.",
    ),
    SettingSpec(
        name="close_with_game",
        kind="bool",
        default=True,
        tab="App",
        label="Close when the game exits",
        tip="Quit automatically (after saving) when the game exits.",
    ),
    SettingSpec(
        name="game_process",
        kind="text",
        default="assettocorsaevo",
        tab="App",
        label="Game process name contains",
        tip="Part of the game's process name, used to detect that it is running or has closed.",
    ),
    SettingSpec(
        name="pause_hotkey",
        kind="hotkey",
        default=DEFAULT_PAUSE_HOTKEY,
        tab="App",
        label="Global pause hotkey",
        tip=(
            "Click the field and press the combination. Ctrl, Alt, Shift or Win plus a letter,"
            " digit or F1-F12; F-keys may be used alone. Use the clear button to turn it off."
        ),
    ),
    SettingSpec(
        name="use_game_log",
        kind="bool",
        default=True,
        tab="App",
        label="Follow the game's log",
        tip=(
            "Read the game's log for the cuts it reports and the sector splits that mark its own"
            ' lines. Shared memory only shows the first cut of a lap (its "lap valid" flag drops'
            " once); the log records one event per cut and every sector split."
        ),
    ),
    SettingSpec(
        name="game_log_dir",
        kind="text",
        default="",
        tab="App",
        label="Game log folder",
        tip=(
            "Where the game writes its logs. Empty = the usual place under Saved Games"
            " (<profile>/Saved Games/ACE/Logs)."
        ),
    ),
    SettingSpec(
        name="telemetry_hz",
        kind="float",
        default=60.0,
        tab="Diagnostics",
        label="Telemetry rate",
        lo=5.0,
        hi=60.0,
        step=5,
        decimals=0,
        suffix=" Hz",
        tip=(
            "How often telemetry is read. Higher makes live data a little smoother; 60 is plenty."
            " Sector lines are interpolated between samples rather than snapped to them, so it can"
            " refine the estimate only up to the rate the game publishes. A change applies the next"
            " time telemetry starts (after a restart or a reconnection), not to the live capture."
        ),
    ),
    SettingSpec(
        name="debug_logging",
        kind="bool",
        default=False,
        tab="Diagnostics",
        label="Verbose (debug) logging",
        tip=(
            "Write extra detail to the log, including the game's track-limit signals (the race cut"
            " and the lap flag) at every change. Turn it on, reproduce a problem, then share the"
            " log file."
        ),
    ),
    SettingSpec(
        name="window_geometry",
        kind="text",
        default="",
    ),
    SettingSpec(
        name="overlay_x",
        kind="optint",
        default=None,
    ),
    SettingSpec(
        name="overlay_y",
        kind="optint",
        default=None,
    ),
)

SPEC_BY_NAME: dict[str, SettingSpec] = {spec.name: spec for spec in SPECS}
DEFAULTS: dict[str, Any] = {spec.name: spec.default for spec in SPECS}
LIMITS: dict[str, tuple[float, float]] = {
    spec.name: spec.bounds for spec in SPECS if spec.bounds is not None
}
OPTIONAL_INT: frozenset[str] = frozenset(spec.name for spec in SPECS if spec.kind == "optint")

TABS: dict[str, list[SettingSpec]] = {
    tab: [spec for spec in SPECS if spec.tab == tab] for tab in TAB_ORDER
}
HIDDEN: tuple[SettingSpec, ...] = tuple(spec for spec in SPECS if spec.tab is None)

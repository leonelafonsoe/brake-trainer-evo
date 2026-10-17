"""Plain data types shared across the app."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SectorStatus(str, Enum):
    """F1-style sector colouring for the current lap."""

    PENDING = "pending"  # not driven yet (or not counted)
    SLOWER = "slower"  # slower than your kept runs
    GOOD = "good"  # among your fastest runs
    BEST = "best"  # your fastest run of this sector


def group_sizes(n: int, groups: int = 3) -> tuple[int, ...]:
    """Split ``n`` sectors into up to ``groups`` consecutive groups of near-equal size."""
    if n <= 0:
        return ()
    groups = min(groups, n)
    return tuple(n // groups + (1 if i < n % groups else 0) for i in range(groups))


class CueKind(str, Enum):
    WARN = "warn"  # braking point coming up
    HERE = "here"  # braking point is right here


@dataclass(frozen=True, slots=True)
class Sample:
    """One telemetry reading, already reduced to what the engine needs."""

    track: str
    car: str
    length_m: float | None
    pos: float  # normalised lap position, 0..1
    brake: float  # 0..1
    speed_kmh: float
    in_pit: bool
    t: float  # seconds (frame timestamp)
    lap_valid: bool = True  # the game's "lap is still valid" flag
    tyres_out: int = 0  # tyres currently off the track
    cut_gained_ms: int = 0  # graphics race-cut: ms gained by the last off-track cut
    cut_deadline_m: int = 0  # graphics race-cut: distance left to give that time back
    cut_delta_s: float = 0.0  # graphics race-cut: delta vs the cleanly-driven reference
    timing_invalid: bool = False  # graphics timing state: the current lap marked invalid
    steer: float = 0.0  # -1..1 steering input, so corners that need no braking can be found


@dataclass(slots=True)
class SectorRun:
    """One clean pass through a sector: its duration and where braking started."""

    t: float
    onsets: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.t, "onsets": self.onsets}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SectorRun:
        return cls(float(raw["t"]), [float(p) for p in raw.get("onsets", [])])


@dataclass(slots=True)
class TrackData:
    """Everything learned for one track + car combination."""

    track: str
    car: str
    n_sectors: int
    sectors: list[list[SectorRun]]  # per sector, fastest run first
    boundaries: list[float] | None = None  # the n-1 inner sector lines; None = equal splits

    @classmethod
    def empty(cls, track: str, car: str, n_sectors: int) -> TrackData:
        return cls(track, car, n_sectors, [[] for _ in range(n_sectors)])

    def total_runs(self) -> int:
        return sum(len(runs) for runs in self.sectors)

    def sectors_with_data(self) -> int:
        return sum(1 for runs in self.sectors if runs)

    def best_total(self) -> float:
        return sum(runs[0].t for runs in self.sectors if runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "track": self.track,
            "car": self.car,
            "n_sectors": self.n_sectors,
            "boundaries": self.boundaries,
            "sectors": [[r.to_dict() for r in runs] for runs in self.sectors],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TrackData:
        n = int(raw["n_sectors"])
        sectors = [[SectorRun.from_dict(r) for r in runs] for runs in raw["sectors"]]
        if len(sectors) != n:
            raise ValueError("sector count mismatch")
        bounds: list[float] | None = None
        raw_bounds = raw.get("boundaries")
        if isinstance(raw_bounds, list) and len(raw_bounds) == n - 1:
            values = [float(b) for b in raw_bounds]
            if all(0.0 < b < 1.0 for b in values) and values == sorted(values):
                bounds = values
        return cls(str(raw["track"]), str(raw["car"]), n, sectors, bounds)


@dataclass(frozen=True, slots=True)
class SectorResult:
    """What happened when a sector was completed."""

    sector: int
    duration: float | None  # None when the pass wasn't counted
    accepted: bool  # became one of the kept (fastest) runs
    best: float | None
    note: str
    braking_events: int = 0
    status: SectorStatus = SectorStatus.PENDING

    def describe(self) -> str:
        label = f"S{self.sector + 1}"
        if self.duration is None:
            return f"{label} {self.note}"
        best = f" (best {self.best:.2f}s)" if self.best is not None else ""
        return f"{label} {self.duration:.2f}s {self.note}{best}"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Read-only view of the engine for the UI."""

    track: str | None = None
    car: str | None = None
    n_sectors: int = 0
    length_m: float = 0.0
    sector: int | None = None
    sector_elapsed: float | None = None
    sector_progress: float = 0.0  # 0..1 through the current sector
    sector_status: tuple[SectorStatus, ...] = ()
    pos: float = 0.0
    speed_kmh: float = 0.0
    brake: float = 0.0
    braking: bool = False
    zones: tuple[float, ...] = ()
    next_zone_m: float | None = None
    lead_m: float = 0.0
    best_times: tuple[float | None, ...] = ()
    reference_car: str | None = None
    reference_sectors: tuple[int, ...] = ()
    warming_up: bool = False  # still inside the ignored warm-up laps
    boundaries: tuple[float, ...] = ()  # sector lines, including 0.0 and 1.0
    equal_lines: bool = False  # stored data uses equal splits (older version or survey off)
    last_result_age: float | None = None  # seconds since the last sector result
    pass_flag: str = ""  # why the current sector will not count ("lap invalidated", ...)
    last_result: SectorResult | None = None
    # A cut the log reported for a lap the sector bar no longer shows (the game buffers its log, so
    # a report can arrive a lap late). There is nothing left on the bar to grey, so the status line
    # says it instead.
    late_cut: str = ""
    late_cut_age: float | None = None  # seconds since that report


@dataclass(frozen=True, slots=True)
class ViewState:
    """What the UI shows: engine snapshot plus connection status."""

    snapshot: Snapshot
    game_running: bool = False
    live: bool = False  # telemetry samples are arriving right now

"""Plain data types shared across the app."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Bumped when a change to TrackData.to_dict would make an older build misread a file. The loader
# refuses a newer version instead of filing runs under boundaries or fields it does not understand;
# the app version in the same file is provenance only. See docs/DATA.md.
DATA_VERSION = 1


class NewerDataError(ValueError):
    """The file was written by a newer learned-data layout than this build understands."""


class SectorStatus(str, Enum):
    """F1-style sector colouring for the current lap."""

    PENDING = "pending"  # not driven yet (or not counted)
    SLOWER = "slower"  # slower than your kept runs
    GOOD = "good"  # among your fastest runs
    BEST = "best"  # your fastest run of this sector


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
    cut_gained_ms: int = 0  # graphics race-cut: ms gained by the last off-track cut
    cut_deadline_m: int = 0  # graphics race-cut: distance left to give that time back
    cut_delta_s: float = 0.0  # graphics race-cut: delta vs the cleanly-driven reference
    timing_invalid: bool = False  # graphics timing state: the current lap marked invalid


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
    boundaries: list[float] | None = None  # the game's n-1 inner sector lines; None = not learned
    # Where braking started on the passes that only the sector lines kept from counting - driven
    # while the lines were still being found, or after they had changed under the car. Their times
    # are worthless, their braking points are not: they are positions on the track, and on a new
    # track they are all there is until a sector has been timed. One list per pass, so a pass counts
    # once towards the half the runs a corner needs; the runs that count out-vote them as they come.
    early_onsets: list[list[float]] = field(default_factory=list)

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
            "version": DATA_VERSION,
            "track": self.track,
            "car": self.car,
            "n_sectors": self.n_sectors,
            "boundaries": self.boundaries,
            "sectors": [[r.to_dict() for r in runs] for runs in self.sectors],
            "early_onsets": [[float(p) for p in chunk] for chunk in self.early_onsets],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TrackData:
        version = int(raw.get("version", DATA_VERSION))
        if version > DATA_VERSION:
            raise NewerDataError(f"data version {version} is newer than {DATA_VERSION}")
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
        return cls(
            str(raw["track"]),
            str(raw["car"]),
            n,
            sectors,
            bounds,
            cls._early_onsets(raw.get("early_onsets")),
        )

    @staticmethod
    def _early_onsets(raw: Any) -> list[list[float]]:
        if not isinstance(raw, list):
            return []
        keep = [
            [float(p) for p in chunk if isinstance(p, int | float)]
            for chunk in raw
            if isinstance(chunk, list)
        ]
        return [chunk for chunk in keep if chunk]


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
    previous_best: float | None = None  # the sector's best before this run, if it was beaten

    @property
    def delta(self) -> float | None:
        """Seconds this run was off the sector's best kept time (negative = a new best).

        A new best has nothing slower to be compared with, so it is measured against the best it
        replaced; the first run of a sector has neither and shows no delta.
        """
        if self.duration is None:
            return None
        if self.status is SectorStatus.BEST:
            if self.previous_best is None:
                return None
            return self.duration - self.previous_best
        if self.best is None:
            return None
        return self.duration - self.best

    def describe(self) -> str:
        label = f"S{self.sector + 1}"
        if self.duration is None:
            return f"{label} {self.note}"
        tail = ""
        if self.best is not None:
            tail = f" (best {self.best:.2f}s"
            if self.delta is not None:
                tail += f", {self.delta:+.2f}s"
            tail += ")"
        return f"{label} {self.duration:.2f}s {self.note}{tail}"


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
    warming_up: bool = False  # still inside the ignored warm-up laps, or learning the sector lines
    warmup_laps_left: int = 0  # of those, how many warm-up laps are left (0 = the lines are why)
    boundaries: tuple[float, ...] = ()  # sector lines, including 0.0 and 1.0
    equal_lines: bool = False  # the game's sector lines are not learned: equal splits are in use
    last_result_age: float | None = None  # seconds since the last sector result
    pass_flag: str = ""  # why the current sector will not count ("lap invalidated", ...)
    last_result: SectorResult | None = None
    # A cut the log reported for a lap the sector bar no longer shows (the game buffers its log, so
    # a report can arrive a lap late). There is nothing left on the bar to grey, so the status line
    # says it instead.
    late_cut: str = ""
    late_cut_age: float | None = None  # seconds since that report
    # A learned-data file this build could not read, or a write that failed and has not succeeded
    # since. The Data tab has the full detail; the status line only needs to tell the driver that
    # the entry was not loaded (or is read-only) or that what they just drove was not saved.
    storage_warning: str = ""


@dataclass(frozen=True, slots=True)
class ViewState:
    """What the UI shows: engine snapshot plus connection status."""

    snapshot: Snapshot
    game_running: bool = False
    live: bool = False  # telemetry samples are arriving right now
    error: str = ""  # a telemetry failure the UI should show, or ""

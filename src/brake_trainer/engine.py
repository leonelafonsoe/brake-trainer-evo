"""Braking-point learning engine.

Pure logic: it consumes :class:`Sample` objects one at a time and reports cues and sector
results through callbacks. The only I/O is the injected :class:`TrackStore`.
"""

from __future__ import annotations

import logging
import statistics
from bisect import bisect_right
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .config import Settings
from .models import CueKind, Sample, SectorResult, SectorRun, SectorStatus, Snapshot, TrackData
from .storage import DataEdit, TrackStore

log = logging.getLogger(__name__)

DEFAULT_LENGTH_M = 5000.0
_COVERAGE_REQUIRED = 0.9  # share of a sector that must be driven for it to count


def sector_count(settings: Settings, length_m: float) -> int:
    """Number of sectors for a track: the user's fixed value, or ~1 per sector_length_m."""
    if settings.n_sectors:
        return settings.n_sectors
    auto = round(length_m / settings.sector_length_m)
    return max(settings.min_sectors, min(settings.max_sectors, auto))


def build_zones(
    sectors: Sequence[Sequence[SectorRun]], cluster_m: float, length_m: float
) -> list[float]:
    """Braking zones (normalised positions) from the kept runs of every sector.

    Onsets within ``cluster_m`` of each other form one corner; a corner must appear in at
    least half of the sector's runs. The zone is the median onset of its cluster.
    """
    gap = cluster_m / length_m
    zones: list[float] = []
    for runs in sectors:
        points = sorted((p, i) for i, run in enumerate(runs) for p in run.onsets)
        if not points:
            continue
        needed = (len(runs) + 1) // 2
        clusters: list[list[tuple[float, int]]] = [[points[0]]]
        for prev, cur in zip(points, points[1:], strict=False):
            if cur[0] - prev[0] > gap:
                clusters.append([])
            clusters[-1].append(cur)
        for cluster in clusters:
            if len({i for _, i in cluster}) >= needed:
                zones.append(statistics.median(p for p, _ in cluster))
    return merge_zones(zones, cluster_m, length_m)


def merge_zones(zones: Sequence[float], cluster_m: float, length_m: float) -> list[float]:
    """Sort zones and drop duplicates closer than ``cluster_m`` (also across the line)."""
    gap = cluster_m / length_m
    merged: list[float] = []
    for z in sorted(zones):
        if not merged or z - merged[-1] > gap:
            merged.append(z)
    if len(merged) > 1 and merged[0] + 1.0 - merged[-1] <= gap:
        merged.pop()
    return merged


_CORNER_SPAN_M = 250.0  # braking point -> past the corner
_LEAD_SPAN_M = 150.0  # the cue warns this far before a braking point

# Flags shown on the overlay for the sector in progress (in priority order).
_PASS_FLAGS = ("lap invalidated", "off track")

# The lap flag and the log's cut notification describe the same event a moment apart; a second
# report within this long is folded into the first.
_DUPLICATE_REPORT_S = 2.0

# How much of the recent sample history to keep, so a cut can be attributed from the position the
# car had when the game wrote the line. The game's log is buffered, so a line can be read a dozen
# seconds late, and the cut itself is a give-back window behind that; this covers both, with room.
_HISTORY_S = 180.0

# Shown when the game invalidates a lap that the app saw no off-track for (no race cut, no tyres
# off the track, no cut in its log): the game judged it from something it does not expose per
# violation, so the sector it happened in cannot be identified.
_CUT_WARNING = (
    "The game invalidated the lap, but it reported no off-track for it (no cut in its log, no race "
    "cut and no tyres off the track). The app can then only drop the sector where the lap flag "
    "dropped, not the sector the cut happened in."
)


def race_cut_active(gained_ms: int, deadline_m: int) -> bool:
    """Is the game currently holding a cut against the driver? Both fields are 0 when it is not."""
    return gained_ms > 0 or deadline_m > 0


def full_bounds(n: int, inner: Sequence[float] | None) -> list[float]:
    """All sector lines including 0.0 and 1.0; equal splits unless ``inner`` is given."""
    if inner is None or len(inner) != n - 1:
        inner = [k / n for k in range(1, n)]
    return [0.0, *inner, 1.0]


def _clearance_m(pos: float, zones: Sequence[float], length_m: float) -> float:
    """Distance from ``pos`` to the nearest braking zone (0 when inside one)."""
    worst = float("inf")
    for z in zones:
        past = ((pos - z) % 1.0) * length_m  # metres since the braking point
        ahead = length_m - past  # metres until we reach it again
        if past <= _CORNER_SPAN_M or ahead <= _LEAD_SPAN_M:
            return 0.0
        worst = min(worst, past - _CORNER_SPAN_M, ahead - _LEAD_SPAN_M)
    return worst


def snap_boundaries(n: int, zones: Sequence[float], length_m: float) -> list[float]:
    """The n-1 inner sector lines, each moved to the middle of the nearest straight.

    A line may move up to 35% of a sector from its equal-split position; within that range it
    takes the spot furthest from any braking zone (braking point and the corner after it).
    """
    equal = [k / n for k in range(1, n)]
    if not zones or n < 2:
        return equal
    half, step = 0.35 / n, 10.0 / length_m
    lines: list[float] = []
    for target in equal:
        best, best_key = target, (-1.0, 0.0)
        pos = target - half
        while pos <= target + half:
            key = (_clearance_m(pos, zones, length_m), -abs(pos - target))
            if key > best_key:
                best, best_key = pos, key
            pos += step
        lines.append(best)
    return lines


@dataclass(slots=True)
class _Pass:
    """A sector pass in progress."""

    t0: float
    clean: bool
    coverage: float = 0.0
    onsets: list[float] = field(default_factory=list)
    paused: bool = False  # learning was off during part of this pass
    flagged: str = ""  # comma-separated reasons this pass must not count


@dataclass(slots=True)
class _BrakeEvent:
    pos: float
    speed: float
    peak: float
    counted: bool = False


class BrakeEngine:
    def __init__(
        self,
        settings: Settings,
        store: TrackStore,
        *,
        on_cue: Callable[[CueKind], None] | None = None,
        on_sector: Callable[[SectorResult], None] | None = None,
        on_message: Callable[[str], None] | None = None,
        on_warning: Callable[[str], None] | None = None,
        on_data_changed: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._on_cue = on_cue or (lambda kind: None)
        self._on_sector = on_sector or (lambda result: None)
        self._on_message = on_message or (lambda text: None)
        self._on_warning = on_warning or (lambda text: None)
        self._on_data_changed = on_data_changed or (lambda: None)
        self._pending: deque[DataEdit] = deque()  # edits requested from the UI thread

        self._key: tuple[str, str] | None = None
        self._n = 0
        self._length_m = DEFAULT_LENGTH_M
        self._data: TrackData | None = None
        self._ref: TrackData | None = None
        self._zones: list[float] = []
        self._ref_zones: list[float] = []  # braking points borrowed from another car
        self._reload = False
        self._last: Sample | None = None
        self._last_result: SectorResult | None = None
        self._last_result_t = 0.0
        self._bounds: list[float] = []
        self._needs_survey = False  # sector lines still to be placed (warm-up lap survey)
        self._survey: list[float] = []
        self._survey_cov = 0.0
        self._lap_valid: bool | None = None  # None until the first sample tells us
        self._lap_saw_off = False  # an off-track this lap, so a bare-cut drop is not it
        self._lap_warned = False  # the cut warning was already given for this lap
        self._tyres_over = False  # the tyre count is over the limit right now (for the message)
        self._cut_active = False  # the game's race-cut signal is up right now
        self._cut_gained = 0  # the last race-cut gain it reported, for spotting a new cut
        self._cut_reported_at = 0.0  # when the game last reported a cut, to fold duplicate signals
        self._history: deque[tuple[float, float, bool]] = deque()  # (t, pos, in_pit) recently seen,
        # so a cut the log reports late is still attributed from where the car was when it happened
        self._lap_runs: dict[int, tuple[SectorRun, list[SectorRun]]] = {}  # stored run, and the
        # list it replaced, so a cut the game reports late can be taken back cleanly
        self._prev_tyres_out = 0  # the previous sample's count, for the verbose log
        self._prev_cut_active = False  # the previous sample's race-cut state, for the verbose log
        self._prev_cut_gained = 0
        self._prev_timing_invalid = False
        self._laps_done = 0  # laps completed since leaving the pits / session start
        self._status: list[SectorStatus] = []
        self._prev_pos: float | None = None
        self._sector = 0
        self._pass: _Pass | None = None
        self._last_closed: tuple[int, SectorRun] | None = None
        self._fired_warn: set[float] = set()
        self._fired_here: set[float] = set()
        self._braking = False
        self._event: _BrakeEvent | None = None

    # ------------------------------------------------------------------ public API

    @property
    def settings(self) -> Settings:
        return self._settings

    def apply_settings(self, settings: Settings) -> None:
        """Swap in new settings; takes effect on the next sample (zones are rebuilt)."""
        self._settings = settings
        self._reload = True

    def reset_tracking(self) -> None:
        """Forget the in-progress sector, e.g. after telemetry was interrupted."""
        self._clear_tracking()

    def queue_edit(self, edit: DataEdit) -> None:
        """Ask for a change to the stored data. Safe from any thread; applied on the next
        :meth:`apply_pending` so it cannot race with the engine's own saves."""
        self._pending.append(edit)

    def apply_pending(self) -> bool:
        """Apply queued edits. If one touches the entry in use, it is reloaded from disk
        (otherwise the in-memory copy would be saved back and undo the deletion)."""
        changed = False
        while self._pending:
            edit = self._pending.popleft()
            changed = self._store.apply(edit) or changed
            if (edit.track, edit.car) == self._key:
                self._data, self._key = None, None  # reload at the next sample
        if changed:
            self._on_data_changed()
        return changed

    def flush(self) -> None:
        if self._data is not None:
            self._store.save(self._data)

    def update(self, s: Sample) -> None:
        self.apply_pending()
        if s.length_m:
            self._length_m = s.length_m
        self._ensure_session(s)
        self._last = s

        pos = min(max(s.pos, 0.0), 0.99999)
        sector = self._sector_of(pos)

        self._history.append((s.t, pos, s.in_pit))
        while self._history and self._history[0][0] < s.t - _HISTORY_S:
            self._history.popleft()

        delta, jump = 0.0, False
        if self._prev_pos is not None:
            delta = ((pos - self._prev_pos + 0.5) % 1.0) - 0.5  # signed, wrap-safe
            jump = abs(delta) > 0.05
        self._prev_pos = pos
        if jump or s.in_pit:
            self._survey.clear()
            self._survey_cov = 0.0
        elif delta > 0 and self._needs_survey:
            self._survey_cov += delta

        if self._pass is None or jump:  # start, reset or teleport
            self._restart_pass(sector, s.t)
        elif sector != self._sector:
            if sector == (self._sector + 1) % self._n:  # crossed into the next sector
                self._close_sector(s.t)
                self._sector, self._pass = sector, _Pass(s.t, clean=True)
                if sector == 0:
                    if not s.in_pit:
                        self._laps_done += 1  # crossed the line: one more lap completed
                    self._fired_warn.clear()
                    self._fired_here.clear()
                    self._lap_saw_off = False
                    self._lap_warned = False
                    self._tyres_over = False
                    self._finish_survey()
            else:  # went backwards over a line
                self._restart_pass(sector, s.t)
        elif delta > 0:
            self._pass.coverage += delta
        st = self._settings
        if s.in_pit:
            self._laps_done = 0  # fresh tyres / cold brakes: warm up again
        if self._pass is not None:
            if s.in_pit:
                self._pass.clean = False
            if self._laps_done < st.warmup_laps:
                self._flag("warm-up lap")
            if self._needs_survey:
                self._flag("surveying track")
            self._check_track_limits(s, pos)
            if not self._settings.learning_enabled:
                self._pass.paused = True

        self._lap_valid = s.lap_valid
        self._track_braking(s, pos)
        self._emit_cues(s, pos)

    def snapshot(self) -> Snapshot:
        s = self._last
        if s is None:
            return Snapshot()
        next_m = None
        if self._zones:
            next_m = min(((z - s.pos) % 1.0) * self._length_m for z in self._zones)
        best = (
            tuple(min((r.t for r in runs), default=None) for runs in self._data.sectors)
            if self._data
            else ()
        )
        elapsed = (s.t - self._pass.t0) if self._pass is not None else None
        return Snapshot(
            track=s.track,
            car=s.car,
            n_sectors=self._n,
            length_m=self._length_m,
            sector=self._sector,
            sector_elapsed=elapsed,
            sector_progress=self._progress(s.pos),
            sector_status=tuple(self._status),
            pos=s.pos,
            speed_kmh=s.speed_kmh,
            brake=s.brake,
            braking=self._braking,
            zones=tuple(self._zones),
            next_zone_m=next_m,
            lead_m=self._lead_m(s.speed_kmh),
            best_times=best,
            reference_car=self._ref.car if self._ref else None,
            reference_sectors=tuple(i for i in range(self._n) if self._using_ref(i)),
            warming_up=self._laps_done < self._settings.warmup_laps or self._needs_survey,
            boundaries=tuple(self._bounds),
            equal_lines=bool(
                self._data and self._data.boundaries is None and self._data.total_runs()
            ),
            last_result_age=(s.t - self._last_result_t) if self._last_result else None,
            pass_flag=self._pass_flag(),
            last_result=self._last_result,
        )

    def _pass_flag(self) -> str:
        """The most important reason the sector in progress will not count, or ""."""
        if self._pass is None:
            return ""
        reasons = self._pass.flagged.split(", ")
        return next((flag for flag in _PASS_FLAGS if flag in reasons), "")

    # ------------------------------------------------------------------ session handling

    def _clear_tracking(self) -> None:
        self._prev_pos = None
        self._lap_valid = None
        self._lap_saw_off = False
        self._lap_warned = False
        self._tyres_over = False
        self._cut_active = False
        self._cut_gained = 0
        self._cut_reported_at = 0.0
        self._history.clear()
        self._lap_runs = {}
        self._prev_tyres_out = 0
        self._prev_cut_active = False
        self._prev_cut_gained = 0
        self._prev_timing_invalid = False
        self._sector = 0
        self._pass = None
        self._last_closed = None
        self._fired_warn = set()
        self._fired_here = set()
        self._braking = False
        self._event = None

    def _ensure_session(self, s: Sample) -> None:
        key = (s.track, s.car)
        n = sector_count(self._settings, self._length_m)
        if key != self._key or n != self._n:
            self._key, self._n = key, n
            self._status = [SectorStatus.PENDING] * n
            self._laps_done = 0
            self._data = self._store.load(s.track, s.car, n)
            self._ref = self._store.find_reference(s.track, s.car, n, self._settings.reference_car)
            self._clear_tracking()
            self._setup_bounds()
            self._rebuild_zones()
            self._on_message(
                f"{s.track} / {s.car}: {n} sectors of ~{self._length_m / n:.0f} m, "
                f"{self._data.total_runs()} stored runs, {len(self._zones)} zones"
            )
            if self._data.boundaries is None and self._data.total_runs():
                self._on_message(
                    "This data uses equal sector lines (saved by an older version or with the "
                    "survey off). Delete it in Settings > Data to place them on the straights."
                )
            if self._ref:
                active = [f"S{i + 1}" for i in range(n) if self._using_ref(i)]
                if active:
                    self._on_message(
                        f"Using {self._ref.car} as a rough reference for {', '.join(active)} "
                        "until you have your own runs"
                    )
        elif self._reload:
            self._rebuild_zones()
        self._reload = False

    def _using_ref(self, i: int) -> bool:
        """Is sector ``i`` still using borrowed braking points?

        Borrowed points are matched by track position, so the other car's sector lines do not
        need to match ours.
        """
        if not self._ref_zones or not self._data:
            return False
        lo, hi = self._bounds[i], self._bounds[i + 1]
        borrowed = any(lo <= z < hi for z in self._ref_zones)
        return borrowed and len(self._data.sectors[i]) < self._settings.own_runs_to_replace_ref

    def _rebuild_zones(self) -> None:
        if self._data is None:
            self._zones = []
            return
        cluster, length = self._settings.cluster_m, self._length_m
        self._ref_zones = build_zones(self._ref.sectors, cluster, length) if self._ref else []
        own = [runs for i, runs in enumerate(self._data.sectors) if not self._using_ref(i)]
        zones = build_zones(own, cluster, length)
        zones += [z for z in self._ref_zones if self._using_ref(self._sector_of(z))]
        self._zones = merge_zones(zones, cluster, length)

    # ------------------------------------------------------------------ sectors

    def _flag(self, reason: str) -> None:
        """Add a reason the pass in progress must not count (once per reason)."""
        if self._pass is None:
            return
        reasons = self._pass.flagged.split(", ") if self._pass.flagged else []
        if reason in reasons:
            return
        reasons.append(reason)
        self._pass.flagged = ", ".join(reasons)

    def _tyres_out_limit(self, lap_valid: bool) -> int:
        """Tyres off the track that drop the sector in progress (0 = never).

        While the lap is valid the strict limit applies, i.e. the count the game itself invalidates
        on. Once the game has invalidated the lap its ``is_valid_lap`` flag stays down and cannot
        report a second mistake, so the lower "once the lap is invalid" limit stands in for it in
        the remaining sectors of that lap.
        """
        st = self._settings
        limits = [st.max_tyres_out]
        if st.skip_invalid_sectors and not lap_valid:
            limits.append(st.max_tyres_out_after_invalid)
        return min((n for n in limits if n), default=0)

    def _check_track_limits(self, s: Sample, pos: float) -> None:
        """Track limits and other infractions, from the game's telemetry.

        The game's own signals, in the frames the app already reads:

        * ``is_valid_lap`` is a *one-shot* state: it drops when the game invalidates the lap and
          stays down until the lap ends, so on its own it can only mark one cut per lap. The game
          reports the cut only after its give-back window, so the sector is taken from behind the
          flag (``cut_give_back_m``);
        * the race-cut pair (time gained and the distance left to give it back) is filled in for
          every off-track, where the game publishes it;
        * ``number_of_tyres_out`` is a live count, where the game publishes it.

        A second cut in an already-invalid lap comes from the game's log (see
        :meth:`report_infraction`), which the app follows for exactly that event.

        An infraction the game judges from something it does not expose (no cut in its log, no race
        cut and no tyres off the track) cannot be pinned to a sector; that is said out loud (a
        warning) rather than guessed at.
        """
        if log.isEnabledFor(logging.DEBUG):  # verbose mode: trace the signals as they change
            self._trace_track_limits(s, pos)
        self._check_race_cut(s, pos)
        self._check_tyres_out(s, pos)
        self._check_lap_flag(s, pos)

    def _check_race_cut(self, s: Sample, pos: float) -> None:
        """The game's per-excursion track-limits signal: the race-cut pair.

        A cut is up while either field is set. A *new* cut is the pair coming up, or the gained
        time changing to another positive value (a second off while the first is still pending). The
        deadline counts down on its own in between, which is not a new cut.
        """
        active = race_cut_active(s.cut_gained_ms, s.cut_deadline_m)
        gained_is_new = s.cut_gained_ms > 0 and s.cut_gained_ms != self._cut_gained
        new_cut = active and (not self._cut_active or gained_is_new)
        self._cut_active, self._cut_gained = active, s.cut_gained_ms
        if not new_cut:
            return
        self._lap_saw_off = True
        self._on_message(f"Off the track at {pos:.0%} of the lap: this sector will not count")
        self._flag("off track")

    def _check_tyres_out(self, s: Sample, pos: float) -> None:
        """The live tyre count: drop the sector while enough tyres are off the track."""
        st = self._settings
        if st.max_tyres_out and s.tyres_out >= st.max_tyres_out:
            self._lap_saw_off = True  # at least one full off this lap: not a bare cut
        limit = self._tyres_out_limit(s.lap_valid)
        over = bool(limit) and s.tyres_out >= limit
        if over and not self._tyres_over:  # a new excursion, not the same one still under way
            self._on_message(
                f"{s.tyres_out} tyres off the track at {pos:.0%} of the lap: "
                "this sector will not count"
            )
        self._tyres_over = over
        if over:
            self._flag("off track")

    def _check_lap_flag(self, s: Sample, pos: float) -> None:
        """The one-shot lap flag: drop the sector the infraction happened in.

        The flag drops when the game has finished judging a cut, which is its give-back window
        (``cut_give_back_m``) after the cut, so the sector it happened in is behind the flag.
        """
        if not self._settings.skip_invalid_sectors or s.lap_valid or self._lap_valid is False:
            return
        fresh = bool(self._lap_valid)  # a fresh drop, not the state the app found at start-up
        where = pos if s.in_pit else self._infraction_pos(pos)
        took_back = self._attribute("lap invalidated", where)
        duplicate = abs(s.t - self._cut_reported_at) < _DUPLICATE_REPORT_S
        self._cut_reported_at = s.t
        if not fresh or duplicate:
            return
        self._on_message(
            f"The game invalidated the lap at {where:.0%} of the lap: {self._note(took_back)}"
        )
        if self._lap_saw_off or self._lap_warned:
            return
        self._lap_warned = True
        if self._settings.use_game_log:
            # The log reports every cut - including this one, a few seconds later - so it is the
            # authority on the sector the cut happened in; only note the fallback, do not warn.
            log.debug("limits: lap flag dropped with no cut seen yet; the log may still explain it")
        else:
            self._on_warning(_CUT_WARNING)

    def report_infraction(self, reason: str, at: float) -> None:
        """The game's log reported a cut; drop the sector it happened in.

        Called from the log tail (same thread as :meth:`update`). ``at`` is when the game wrote the
        line: the game buffers its log, so it can be read seconds later, and a whole lap's cuts can
        arrive in one read. Attributing from the car's position at ``at`` keeps each of them in its
        own sector.
        """
        s = self._last
        if s is None or self._pass is None or not self._settings.skip_invalid_sectors:
            return
        self._lap_saw_off = True  # the game did report a cut: the bare-cut warning does not apply
        if abs(at - self._cut_reported_at) < _DUPLICATE_REPORT_S:
            return  # the lap flag already stood for this same cut
        self._cut_reported_at = at
        pos, in_pit = self._pos_at(at)
        where = pos if in_pit else self._infraction_pos(pos)
        took_back = self._attribute("off track", where)
        log.debug(
            "limits: %s written at %.3f (read %.1f s later), car at %.1f%% (S%d), "
            "attributed %s at %.1f%% (S%d), run %s",
            reason,
            at,
            s.t - at,
            pos * 100.0,
            self._sector_of(pos) + 1,
            f"{self._settings.cut_give_back_m:.0f} m back",
            where * 100.0,
            self._sector_of(where) + 1,
            "taken back" if took_back else "not stored",
        )
        self._on_message(f"{reason} at {where:.0%} of the lap: {self._note(took_back)}")

    def _pos_at(self, at: float) -> tuple[float, bool]:
        """Where the car was (position, in the pits) when the game wrote a report at time ``at``.

        Falls back to the latest sample when ``at`` is outside the kept history, or ahead of it,
        which a little clock skew between the log and the telemetry can do.
        """
        s = self._last
        if s is not None and at >= s.t:
            return min(max(s.pos, 0.0), 0.99999), s.in_pit
        for ts, pos, in_pit in reversed(self._history):
            if ts <= at:
                return pos, in_pit
        return (min(max(s.pos, 0.0), 0.99999), s.in_pit) if s is not None else (0.0, False)

    @staticmethod
    def _note(took_back: bool) -> str:
        return "its stored run was taken back" if took_back else "this sector will not count"

    def _infraction_pos(self, pos: float) -> float:
        """The lap position a report arriving at ``pos`` is really about.

        The game only reports a cut once the driver has failed to give the time back within its
        give-back window, so the cut happened ``cut_give_back_m`` of track behind the report.
        """
        back = self._settings.cut_give_back_m / max(self._length_m, 1.0)
        return (pos - back) % 1.0

    def _attribute(self, reason: str, where: float) -> bool:
        """Make the sector at ``where`` not count; True if a stored run was taken back.

        The sector may still be in progress (the pass is flagged) or already closed this lap (its
        stored run is removed, since the game reported the cut too late to stop it being saved).
        A closed sector is shown as not counted either way, even when it had no run to take back.
        """
        idx = self._sector_of(where)
        if idx == self._sector:
            self._flag(reason)
            return False
        if 0 <= idx < len(self._status):
            self._status[idx] = SectorStatus.PENDING
        return self._drop_run(idx)

    def _drop_run(self, idx: int) -> bool:
        """Take back the run this lap stored for sector ``idx``; True if there was one to take.

        The whole previous list is restored, not just the new run removed: keeping the top runs
        already discarded the one it displaced.
        """
        entry = self._lap_runs.pop(idx, None)
        if entry is None or self._data is None:
            return False
        run, previous = entry
        self._data.sectors[idx] = previous
        if self._last_closed is not None and self._last_closed[1] is run:
            self._last_closed = None
        self._rebuild_zones()
        self._store.save(self._data)
        return True

    def _trace_track_limits(self, s: Sample, pos: float) -> None:
        """Verbose log of the game's track-limit signals, only when one of them changes.

        This is the detail a report about a missed sector needs: what the game actually reported
        and when, with the position and sector. Off unless verbose logging is on.
        """
        if s.tyres_out != self._prev_tyres_out:
            log.debug(
                "limits: tyres_out %d -> %d at %.1f%% of the lap (lap_valid=%s, limit=%d, S%d)",
                self._prev_tyres_out,
                s.tyres_out,
                pos * 100.0,
                s.lap_valid,
                self._tyres_out_limit(s.lap_valid),
                self._sector + 1,
            )
            self._prev_tyres_out = s.tyres_out
        active = race_cut_active(s.cut_gained_ms, s.cut_deadline_m)
        if active != self._prev_cut_active or s.cut_gained_ms != self._prev_cut_gained:
            log.debug(
                "limits: race_cut %s at %.1f%% of the lap "
                "(gained=%d ms, deadline=%d m, delta=%+.2f s, S%d)",
                "up" if active else "clear",
                pos * 100.0,
                s.cut_gained_ms,
                s.cut_deadline_m,
                s.cut_delta_s,
                self._sector + 1,
            )
            self._prev_cut_active = active
            self._prev_cut_gained = s.cut_gained_ms
        if s.timing_invalid != self._prev_timing_invalid:
            log.debug(
                "limits: timing_invalid %s -> %s at %.1f%% of the lap (S%d)",
                self._prev_timing_invalid,
                s.timing_invalid,
                pos * 100.0,
                self._sector + 1,
            )
            self._prev_timing_invalid = s.timing_invalid
        if s.lap_valid != self._lap_valid:
            where = self._infraction_pos(pos)
            log.debug(
                "limits: lap_valid %s -> %s at %.1f%% of the lap (S%d); cut attributed %.0f m back "
                "at %.1f%% (S%d)",
                self._lap_valid,
                s.lap_valid,
                pos * 100.0,
                self._sector + 1,
                self._settings.cut_give_back_m,
                where * 100.0,
                self._sector_of(where) + 1,
            )

    def _sector_of(self, pos: float) -> int:
        return min(max(bisect_right(self._bounds, pos) - 1, 0), self._n - 1)

    def _progress(self, pos: float) -> float:
        pos = min(max(pos, 0.0), 0.99999)
        k = self._sector_of(pos)
        lo, hi = self._bounds[k], self._bounds[k + 1]
        return min(max((pos - lo) / (hi - lo), 0.0), 1.0)

    def _setup_bounds(self) -> None:
        """Pick the sector lines for this track + car (stored, borrowed, or surveyed later)."""
        data = self._data
        assert data is not None
        self._survey, self._survey_cov, self._needs_survey = [], 0.0, False
        fresh = data.boundaries is None and not data.total_runs()
        if fresh and self._ref is not None and self._ref.boundaries:
            data.boundaries = list(self._ref.boundaries)  # share the other car's lines
        elif fresh:
            st = self._settings
            self._needs_survey = st.snap_sector_boundaries and st.warmup_laps > 0
        self._bounds = full_bounds(self._n, data.boundaries)

    def _finish_survey(self) -> None:
        """End of the warm-up lap: place the sector lines on the straights it revealed."""
        if not self._needs_survey or self._data is None:
            return
        if self._laps_done < self._settings.warmup_laps or self._survey_cov < 0.9:
            return  # not a complete lap yet
        self._needs_survey = False
        zones = build_zones(
            [[SectorRun(0.0, list(self._survey))]], self._settings.cluster_m, self._length_m
        )
        self._survey.clear()
        if not zones:
            return
        inner = snap_boundaries(self._n, zones, self._length_m)
        self._data.boundaries = inner
        self._bounds = full_bounds(self._n, inner)
        self._on_message(f"Sector lines placed on the straights ({len(zones)} corners surveyed)")
        if self._settings.learning_enabled:
            self._store.save(self._data)

    def _restart_pass(self, sector: int, t: float) -> None:
        self._sector, self._pass, self._last_closed = sector, _Pass(t, clean=False), None
        self._fired_warn.clear()
        self._fired_here.clear()

    def _report(self, result: SectorResult) -> None:
        self._last_result = result
        self._last_result_t = self._last.t if self._last else 0.0
        self._on_sector(result)
        self._on_message(result.describe())

    def _close_sector(self, t: float) -> None:
        run, idx, data = self._pass, self._sector, self._data
        self._last_closed = None
        self._lap_runs.pop(idx, None)  # this run is being replaced; only what we store now counts
        if run is None or data is None:
            return
        learning = self._settings.learning_enabled
        if idx == 0:  # a new lap's first sector is done: clear last lap's colours
            self._status = [SectorStatus.PENDING] * self._n
        if not run.clean:
            note = "not counted (pit, reset or partial)"
            self._report(SectorResult(idx, None, False, None, note))
            return
        if run.flagged:
            note = f"not counted ({run.flagged})"
            self._report(SectorResult(idx, None, False, None, note))
            return
        if learning and run.paused:
            note = "not counted (learning was paused)"
            self._report(SectorResult(idx, None, False, None, note))
            return
        width = self._bounds[idx + 1] - self._bounds[idx]
        if run.coverage < _COVERAGE_REQUIRED * width:
            share = run.coverage / width
            self._report(SectorResult(idx, None, False, None, f"not counted ({share:.0%} covered)"))
            return

        was_ref = learning and self._using_ref(idx)
        stored = SectorRun(round(t - run.t0, 3), list(run.onsets))
        kept = sorted([*data.sectors[idx], stored], key=lambda r: r.t)[: self._settings.top_runs]
        accepted = any(r is stored for r in kept)
        if kept[0] is stored:
            self._status[idx] = SectorStatus.BEST
        elif accepted:
            self._status[idx] = SectorStatus.GOOD
        else:
            self._status[idx] = SectorStatus.SLOWER

        if learning:
            previous = list(data.sectors[idx])  # so a late cut report can put it back
            data.sectors[idx] = kept
            if accepted:
                self._last_closed = (idx, stored)
                self._lap_runs[idx] = (stored, previous)
                self._rebuild_zones()
                self._store.save(data)
        # with learning off the colours still show how the sector compared, but nothing is stored
        note = ("kept" if learning else "would be kept") if accepted else "not faster"
        status = self._status[idx]
        self._report(
            SectorResult(idx, stored.t, accepted, kept[0].t, note, len(stored.onsets), status)
        )
        if was_ref and not self._using_ref(idx):
            self._on_message(f"S{idx + 1}: now using your own braking points for this car")

    # ------------------------------------------------------------------ braking events

    def _track_braking(self, s: Sample, pos: float) -> None:
        st = self._settings
        if not self._braking and s.brake >= st.brake_on:
            self._braking = True
            self._event = _BrakeEvent(pos, s.speed_kmh, s.brake)
        elif self._braking and self._event is not None:
            e = self._event
            e.peak = max(e.peak, s.brake)
            shed = e.speed - s.speed_kmh
            if not e.counted and e.peak >= st.min_peak and shed >= st.min_speed_drop:
                e.counted = True
                self._add_onset(e.pos)
            if s.brake <= st.brake_off:
                self._braking, self._event = False, None

    def _add_onset(self, pos: float) -> None:
        if self._needs_survey:
            self._survey.append(pos)
        if not self._settings.learning_enabled:
            return
        sector = self._sector_of(pos)
        pos = round(pos, 5)
        if self._pass is not None and sector == self._sector:
            self._pass.onsets.append(pos)
        elif self._last_closed and self._last_closed[0] == sector and self._data:
            # confirmed just after the sector line: add to the run that was just saved
            self._last_closed[1].onsets.append(pos)
            self._rebuild_zones()
            self._store.save(self._data)

    # ------------------------------------------------------------------ cues

    def _lead_m(self, speed_kmh: float) -> float:
        st = self._settings
        return max(st.min_lead_m, max(speed_kmh / 3.6, 0.1) * st.lead_s)

    def _emit_cues(self, s: Sample, pos: float) -> None:
        st = self._settings
        lead = self._lead_m(s.speed_kmh)
        for z in self._zones:
            dist = ((z - pos) % 1.0) * self._length_m
            if dist > self._length_m / 2:
                dist -= self._length_m  # the point is behind us
            if abs(dist) <= st.here_m and z not in self._fired_here:
                self._fired_here.add(z)
                if s.brake < st.skip_zone_if_braking:
                    self._on_cue(CueKind.HERE)
            elif st.here_m < dist <= lead and z not in self._fired_warn:
                self._fired_warn.add(z)
                if s.brake < st.skip_zone_if_braking:
                    self._on_cue(CueKind.WARN)

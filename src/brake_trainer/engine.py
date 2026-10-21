"""Braking-point learning engine.

Pure logic: it consumes :class:`Sample` objects one at a time and reports cues and sector
results through callbacks. The only I/O is the injected :class:`TrackStore`.

Sector lines are the game's own: every lap is scored in three sectors and the game writes each
split to its log, so the two inner lines are learned from there (see
:meth:`BrakeEngine.report_split`) rather than invented here.
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

# The game scores every lap in three sectors and shows three splits. The app uses the same three,
# so its sectors are the ones the game reports; only the two inner lines have to be found, which is
# what the game's split lines in its log are for.
N_SECTORS = 3
# A log that never brings a split (following it is off, or this build does not write them) would
# otherwise leave every lap uncounted, so the equal splits are settled for after this many laps.
_LINES_WAIT_LAPS = 3
# A pass in progress when the lines are learned is only kept if it began on a line that both
# layouts share (in practice the start/finish line). This is how close its start has to be to one:
# a few metres of lap, far inside the gap between an equal split and the game's own line.
_LINE_MATCH = 0.001


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


# Flags shown on the overlay for the sector in progress (in priority order).
_PASS_FLAGS = ("lap invalidated", "off track")

# Reasons a pass cannot count that say nothing about the sector bar: the lap is a warm-up one, or it
# was driven while the sector lines were still being found or had just changed under the car. The
# status line already says so, and a flag on top of it would read as if it were the reason.
_NOT_COUNTING_ANYWAY = ("warm-up lap", "finding the sector lines")

# When several reasons apply to the same sector, name the one that explains it best. A result note
# with every reason reads like a stack trace, and the later ones add nothing the driver needs.
_NOTE_PRIORITY = (
    "warm-up lap",
    "finding the sector lines",
    "the lines were learned mid-sector",
    "off track",
    "lap invalidated",
)


def _note(reasons: set[str]) -> str:
    """The one reason worth showing for a sector that did not count."""
    for reason in _NOTE_PRIORITY:
        if reason in reasons:
            return reason
    return ", ".join(sorted(reasons))


# The reasons a pass may carry and still have its braking points kept (see TrackData.early_onsets).
_LINES_REASONS = frozenset({"finding the sector lines", "the lines were learned mid-sector"})

# How much of the recent sample history to keep, so a cut can be attributed from the position the
# car had when the game wrote the line. The game buffers its log (a few KB, flushed when full), so a
# cut can be read a whole lap after it was judged - the give-back window is behind that again - so
# this covers a lap or two of driving at any sane rate.
_HISTORY_S = 300.0

# How many laps back a late cut can still take its sector's stored run back from. Only the runs of
# the last few laps are worth keeping for that.
_RUNS_KEPT_LAPS = 3

# Shown when the game invalidates a lap that the app saw no off-track for (no race cut, no tyres
# off the track, no cut in its log): the game judged it from something it does not expose per
# violation, so the sector it happened in cannot be identified.
_CUT_WARNING = (
    "The game invalidated the lap with no race cut, no tyres off the track and no cut in its log, "
    "so the sector it happened in cannot be identified: only the sector where the flag dropped "
    "will be dropped."
)


def race_cut_active(gained_ms: int, deadline_m: int) -> bool:
    """Is the game currently holding a cut against the driver? Both fields are 0 when it is not."""
    return gained_ms > 0 or deadline_m > 0


def _split_position_ok(index: int, pos: float) -> bool:
    """Could a split at ``pos`` be the sector line it should be, rather than a stray one?

    The game's own lines are roughly equal thirds of the lap (at Monza, 32% and 63%), so each is
    looked for in its own half with room to spare. This catches a teleport or a reset landing in
    the middle of a lap; a split written on an out-lap is just as good, since the lines belong to
    the track.
    """
    if not 0.05 <= pos <= 0.95:
        return False
    return pos <= 0.6 if index == 0 else pos >= 0.4


def full_bounds(n: int, inner: Sequence[float] | None) -> list[float]:
    """All sector lines including 0.0 and 1.0; equal splits unless ``inner`` is given."""
    if inner is None or len(inner) != n - 1:
        inner = [k / n for k in range(1, n)]
    return [0.0, *inner, 1.0]


@dataclass(slots=True)
class _Pass:
    """A sector pass in progress."""

    t0: float
    clean: bool
    start_pos: float = 0.0  # where it began, so a changed sector line can tell if it is still valid
    coverage: float = 0.0
    onsets: list[float] = field(default_factory=list)
    paused: bool = False  # learning was off during part of this pass
    flagged: set[str] = field(default_factory=set)  # reasons this pass must not count


@dataclass(slots=True)
class _LostPass:
    """A sector that closed while only the sector lines kept it from counting.

    Held until the lines are known, so the samples can still time it (see
    :meth:`BrakeEngine._retime_lost_sectors`); dropped when they arrive too late for the history.
    """

    lap: int
    sector: int
    end: float  # when it closed, to prune against the kept sample history
    run: _Pass


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
        self._late_cut = ""  # a cut reported for a lap the sector bar no longer shows
        self._late_cut_t = 0.0
        self._bounds: list[float] = []
        # The game's sector lines, still being learned from its split lines: while this is up the
        # laps are not counted, since a run timed between lines that then move would be filed wrong.
        self._learning_lines = False
        self._lines_laps = 0  # laps driven while waiting for the log to bring a split
        # Splits seen (index -> (position, lap, written at)) until both lines of one lap are in.
        self._splits: dict[int, tuple[float, int, float]] = {}
        self._lap_valid: bool | None = None  # None until the first sample tells us
        self._lap_no = 0  # counted up at every line crossing, so a late cut knows its own lap
        self._status_lap = 0  # the lap whose colours _status holds: the last one, until S1 ends
        self._lap_saw_off = False  # an off-track this lap, so a bare-cut drop is not it
        self._lap_warned = False  # the cut warning was already given for this lap
        self._tyres_over = False  # the tyre count is over the limit right now (for the message)
        self._cut_active = False  # the game's race-cut signal is up right now
        self._cut_gained = 0  # the last race-cut gain it reported, for spotting a new cut
        self._cut_deadline = 0  # its give-back distance, which grows again when a new cut starts
        self._history: deque[tuple[float, float, bool, int]] = deque()  # (t, pos, in_pit, lap)
        # recently seen, so a cut the log reports late is still attributed from where the car was
        self._lap_runs: dict[tuple[int, int], tuple[SectorRun, list[SectorRun]]] = {}  # per lap and
        # sector: the run it stored, and the list it replaced, so a cut the game reports a lap late
        # can be taken back cleanly without touching the run a later lap stored for that sector
        self._lines_lost: list[_LostPass] = []  # sectors the lines arrived too late for (yet)
        self._invalid_sectors: set[tuple[int, int]] = set()  # (lap, sector) the game invalidated
        # (lap, sector) -> why it did not count, for sectors already out for another reason. A cut
        # reported later for one of them changes nothing, so its message is not repeated.
        self._lap_notes: dict[tuple[int, int], str] = {}
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

        self._history.append((s.t, pos, s.in_pit, self._lap_no))
        while self._history and self._history[0][0] < s.t - _HISTORY_S:
            self._history.popleft()

        delta, jump = 0.0, False
        if self._prev_pos is not None:
            delta = ((pos - self._prev_pos + 0.5) % 1.0) - 0.5  # signed, wrap-safe
            jump = abs(delta) > 0.05
        self._prev_pos = pos
        if self._pass is None or jump:  # start, reset or teleport
            self._restart_pass(sector, s.t, pos)
        elif sector != self._sector:
            if sector == (self._sector + 1) % self._n:  # crossed into the next sector
                self._close_sector(s.t)
                self._sector, self._pass = sector, _Pass(s.t, clean=True, start_pos=pos)
                if sector == 0:
                    if not s.in_pit:
                        self._laps_done += 1  # crossed the line: one more lap completed
                    self._lap_no += 1  # a new lap: late cuts of the old one no longer mark it
                    self._prune_lap_runs()
                    self._fired_warn.clear()
                    self._fired_here.clear()
                    self._lap_saw_off = False
                    self._lap_warned = False
                    self._tyres_over = False
                    self._lines_watch()
            else:  # went backwards over a line
                self._restart_pass(sector, s.t, pos)
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
            if self._learning_lines:
                self._flag("finding the sector lines")
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
            warming_up=self._laps_done < self._settings.warmup_laps or self._learning_lines,
            warmup_laps_left=max(0, self._settings.warmup_laps - self._laps_done),
            boundaries=tuple(self._bounds),
            equal_lines=bool(
                self._data and self._data.boundaries is None and self._data.total_runs()
            ),
            last_result_age=(s.t - self._last_result_t) if self._last_result else None,
            pass_flag=self._pass_flag(),
            last_result=self._last_result,
            late_cut=self._late_cut,
            late_cut_age=(s.t - self._late_cut_t) if self._late_cut else None,
        )

    def _pass_flag(self) -> str:
        """The most important reason the sector in progress will not count, or ""."""
        if self._pass is None:
            return ""
        if self._pass.flagged.intersection(_NOT_COUNTING_ANYWAY):
            return ""
        return next((flag for flag in _PASS_FLAGS if flag in self._pass.flagged), "")

    # ------------------------------------------------------------------ session handling

    def _clear_tracking(self) -> None:
        self._prev_pos = None
        self._lap_valid = None
        self._lap_no = 0
        self._status_lap = 0
        self._late_cut = ""
        self._late_cut_t = 0.0
        self._lap_saw_off = False
        self._lap_warned = False
        self._tyres_over = False
        self._cut_active = False
        self._cut_gained = 0
        self._cut_deadline = 0
        self._history.clear()
        self._lap_runs = {}
        self._lines_lost.clear()
        self._invalid_sectors.clear()
        self._lap_notes.clear()
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
        n = N_SECTORS
        if key != self._key or n != self._n:
            self._key, self._n = key, n
            self._status = [SectorStatus.PENDING] * n
            self._laps_done = 0
            self._data = self._store.load(s.track, s.car, n)
            self._ref = self._store.find_reference(s.track, s.car, n, self._settings.reference_car)
            self._clear_tracking()
            lines_from = self._store.share_lines(self._data)
            self._setup_bounds()
            self._rebuild_zones()
            self._on_message(
                f"{s.track} / {s.car}: the game's {n} sectors, "
                f"{self._data.total_runs()} stored runs, {len(self._zones)} braking points"
            )
            if lines_from:
                self._on_message(
                    f"Sector lines taken from {lines_from} on this track: the game's own are the "
                    "track's, not the car's"
                )
            if self._data.boundaries is None and not self._learning_lines:
                self._on_message(
                    "Sector lines are equal splits: the game's own were not read (data saved by "
                    "an older version, or 'Follow the game's log' is off). Delete this entry in "
                    "Settings > Data to learn them again."
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

    def _early_runs(self) -> list[list[SectorRun]]:
        """The kept onsets as stand-in runs, one per pass, filed under the sector they fall in.

        The passes were not timed, so they have no time of their own: only their onsets are carried,
        which is all ``build_zones`` looks at. One onset at a time is filed, not one pass at a time,
        because a pass driven on the stand-in equal splits can straddle one of the game's lines.
        """
        runs: list[list[SectorRun]] = [[] for _ in range(self._n)]
        data = self._data
        if data is None:
            return runs
        for chunk in data.early_onsets:
            by_sector: dict[int, list[float]] = {}
            for pos in chunk:
                by_sector.setdefault(self._sector_of(pos), []).append(pos)
            for sector, onsets in by_sector.items():
                runs[sector].append(SectorRun(0.0, onsets))
        return runs

    def _rebuild_zones(self) -> None:
        if self._data is None:
            self._zones = []
            return
        cluster, length = self._settings.cluster_m, self._length_m
        self._ref_zones = build_zones(self._ref.sectors, cluster, length) if self._ref else []
        early = self._early_runs()
        own: list[list[SectorRun]] = [[] for _ in range(self._n)]
        for i, runs in enumerate(self._data.sectors):
            if not self._using_ref(i):
                own[i].extend(runs)
            # The early onsets count either way: they are this car's own driving, not a reference's.
            own[i].extend(early[i])
        zones = build_zones(own, cluster, length)
        zones += [z for z in self._ref_zones if self._using_ref(self._sector_of(z))]
        self._zones = merge_zones(zones, cluster, length)

    def _keep_onsets(self, run: _Pass | None) -> None:
        """Keep where the driver braked in a pass that only the sector lines kept from counting.

        A pass flagged for the lines alone is a pass the driver drove normally through the sector:
        only the app's lack of knowledge of where the lines were (or the lines moving under it) made
        it uncountable. Their times cannot be trusted, but their braking points are positions on the
        track, and on a new track they are all the cues there are until a sector has been timed -
        which, with the game's log buffered, is a lap or two after the driver would like them.
        """
        if (
            self._data is None
            or run is None
            or not run.onsets
            or not run.clean
            or run.paused
            or not self._lines_only(run.flagged)
        ):
            return
        self._data.early_onsets.append(list(run.onsets))
        self._store.save(self._data)
        self._rebuild_zones()

    @staticmethod
    def _lines_only(reasons: set[str]) -> bool:
        """Were the sector lines the only thing keeping this pass from counting?"""
        return bool(reasons) and reasons <= _LINES_REASONS

    def _hold_lost(self, run: _Pass, sector: int, end: float) -> None:
        """Keep a sector the lines arrived too late for, so it can be timed once they do.

        Only one the lines alone kept from counting is worth holding: a warm-up lap, a cut, a pit
        stop or a pause makes the time worthless however the lines are drawn. Once the lines are
        settled (or given up on) nothing will retime it, so nothing is held either.
        """
        reasons = run.flagged
        if not self._learning_lines or not run.clean or run.paused or not self._lines_only(reasons):
            return
        # Older than the samples can reach is no good: the lines would arrive too late to time it.
        self._lines_lost = [x for x in self._lines_lost if x.end >= end - _HISTORY_S]
        self._lines_lost.append(_LostPass(self._lap_no, sector, end, run))

    # ------------------------------------------------------------------ sectors

    def _flag(self, reason: str) -> None:
        """Add a reason the pass in progress must not count (once per reason)."""
        if self._pass is not None:
            self._pass.flagged.add(reason)

    def _unflag(self, reason: str) -> None:
        """Take a reason back: it no longer applies to the pass in progress."""
        if self._pass is not None:
            self._pass.flagged.discard(reason)

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

        The signals overlap: one cut can be seen by the race-cut pair, by the lap flag and in the
        log. Each is attributed to a ``(lap, sector)`` and only the first one to reach it acts, so
        the same cut never drops two sectors (nor says so twice), while two cuts in different
        sectors of one lap each drop their own.
        """
        if log.isEnabledFor(logging.DEBUG):  # verbose mode: trace the signals as they change
            self._trace_track_limits(s, pos)
        self._check_race_cut(s, pos)
        self._check_tyres_out(s, pos)
        self._check_lap_flag(s, pos)

    def _check_race_cut(self, s: Sample, pos: float) -> None:
        """The game's per-excursion track-limits signal: the race-cut pair.

        A cut is up while either field is set. A *new* cut is the pair coming up, the gained time
        changing to another positive value, or the give-back distance growing again (a second off
        while the first is still being handed back, even if it gained the same time). The deadline
        counting down on its own is not a new cut.
        """
        active = race_cut_active(s.cut_gained_ms, s.cut_deadline_m)
        gained_is_new = s.cut_gained_ms > 0 and s.cut_gained_ms != self._cut_gained
        deadline_is_new = s.cut_deadline_m > self._cut_deadline
        new_cut = active and (not self._cut_active or gained_is_new or deadline_is_new)
        self._cut_active, self._cut_gained = active, s.cut_gained_ms
        self._cut_deadline = s.cut_deadline_m
        if not new_cut:
            return
        self._lap_saw_off = True
        idx = self._sector_of(pos)
        quiet = self._already_out(self._lap_no, idx)  # before _attribute flags this pass
        if self._attribute("off track", pos, self._lap_no) is None:
            log.debug(
                "limits: race cut at %.1f%% (S%d) is in a sector already invalidated: not said",
                pos * 100.0,
                idx + 1,
            )
            return
        if quiet:
            log.debug(
                "limits: race cut at %.1f%% (S%d) is in a sector already not counting: not said",
                pos * 100.0,
                idx + 1,
            )
            return
        self._on_message(f"Off the track at {pos:.0%}: S{idx + 1} won't count")

    def _check_tyres_out(self, s: Sample, pos: float) -> None:
        """The live tyre count: drop the sector while enough tyres are off the track."""
        st = self._settings
        if st.max_tyres_out and s.tyres_out >= st.max_tyres_out:
            self._lap_saw_off = True  # at least one full off this lap: not a bare cut
        limit = self._tyres_out_limit(s.lap_valid)
        over = bool(limit) and s.tyres_out >= limit
        new_excursion = over and not self._tyres_over
        self._tyres_over = over
        if not over:
            return
        # Also covers a pass restarted (or a line crossed) while the tyres are still out, so every
        # sector the excursion reaches is dropped, not just the one it began in.
        idx = self._sector_of(pos)
        quiet = self._already_out(self._lap_no, idx)  # before _attribute flags this pass
        dropped = self._attribute("off track", pos, self._lap_no)
        self._flag("off track")
        if new_excursion and dropped is not None and not quiet:
            self._on_message(
                f"{s.tyres_out} tyres off the track at {pos:.0%}: S{idx + 1} won't count"
            )

    def _check_lap_flag(self, s: Sample, pos: float) -> None:
        """The one-shot lap flag: drop the sector the infraction happened in.

        The flag drops when the game has finished judging a cut, which is its give-back window
        (``cut_give_back_m``) after the cut, so the sector it happened in is behind the flag.
        """
        if not self._settings.skip_invalid_sectors or s.lap_valid or self._lap_valid is False:
            return
        fresh = bool(self._lap_valid)  # a fresh drop, not the state the app found at start-up
        where = pos if s.in_pit else self._infraction_pos(pos)
        idx = self._sector_of(where)
        lap = self._infraction_lap(pos, s.in_pit)
        # A pass that already will not count - a warm-up lap, the lines still being learned, or one
        # that began mid-sector - makes this drop a no-op. Say nothing rather than announce a loss
        # the driver has been told about already: the game invalidates an out-lap's opening sector
        # *because* it began in the pits, and the app would otherwise open a session with "S1 won't
        # count".
        run = self._pass if lap == self._lap_no and idx == self._sector else None
        already = self._already_out(lap, idx) or (run is not None and not run.clean)
        took_back = self._attribute("lap invalidated", where, lap)
        if took_back is None:
            log.debug(
                "limits: lap flag fell at %.1f%% (S%d), a sector already invalidated: not said",
                where * 100.0,
                idx + 1,
            )
            return
        if not fresh:
            return
        if already:
            log.debug(
                "limits: lap flag fell at %.1f%% (S%d), which already will not count: not said",
                where * 100.0,
                idx + 1,
            )
            return
        self._on_message(
            f"The game invalidated the lap at {where:.0%}: {self._drop_text(where, took_back)}"
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
        line. The game buffers its log (a few KB, flushed when full), so a cut can be read seconds
        or a whole lap after it was judged, and a whole batch can arrive at once. Each is therefore
        attributed from the car's position *then*, and to the lap it happened in - never to the
        sector of the same number in the lap being driven now.

        One cut can also be seen live (the race-cut pair, the lap flag) and re-read when the game
        restarts its log: a ``(lap, sector)`` the app already invalidated is not dropped again.
        """
        s = self._last
        if s is None or self._pass is None or not self._settings.skip_invalid_sectors:
            return
        found = self._pos_at(at)
        if found is None:
            log.debug(
                "limits: %s written at %.3f is older than the kept history (%.0f s): not used",
                reason,
                at,
                _HISTORY_S,
            )
            return
        pos, in_pit, lap = found
        if lap == self._lap_no:  # a cut of the lap being driven: not a bare lap-flag drop
            self._lap_saw_off = True
        where = pos if in_pit else self._infraction_pos(pos)
        idx = self._sector_of(where)
        quiet = self._already_out(lap, idx)  # before _attribute flags this pass
        took_back = self._attribute("off track", where, lap)
        if took_back is None:
            log.debug(
                "limits: %s written at %.3f invalidates S%d of %s, already invalidated: "
                "not counted twice",
                reason,
                at,
                idx + 1,
                self._laps_back(lap),
            )
            return
        if quiet:
            log.debug(
                "limits: %s written at %.3f invalidates S%d of %s, already not counting: not said",
                reason,
                at,
                idx + 1,
                self._laps_back(lap),
            )
            return
        if lap != self._status_lap:  # the bar does not hold that lap any more: nothing to grey
            lap_word = "the last lap" if self._lap_no - lap == 1 else "an earlier lap"
            self._late_cut = f"S{idx + 1} of {lap_word} won't count · cut"
            self._late_cut_t = s.t
        log.debug(
            "limits: %s written at %.3f (read %.1f s later, %s), car at %.1f%% (S%d), "
            "attributed %s at %.1f%% (S%d), run %s",
            reason,
            at,
            s.t - at,
            self._laps_back(lap),
            pos * 100.0,
            self._sector_of(pos) + 1,
            f"{self._settings.cut_give_back_m:.0f} m back",
            where * 100.0,
            idx + 1,
            "taken back" if took_back else "not stored",
        )
        self._on_message(self._report_text(reason, where, lap, took_back))

    def _report_text(self, reason: str, where: float, lap: int, took_back: bool) -> str:
        """What to tell the driver about a reported cut, always naming the sector it dropped.

        The sector is named rather than called "this sector": on a lap that is over the sector bar
        holds the lap being driven instead, and even on the lap being driven the attributed spot can
        sit on the far side of a line from the sector the driver felt they were in.
        """
        if lap == self._lap_no:
            return f"{reason} at {where:.0%}: {self._drop_text(where, took_back)}"
        return (
            f"{reason}{self._lap_phrase(lap)} at {where:.0%}: {self._drop_text(where, took_back)}"
        )

    def _laps_back(self, lap: int) -> str:
        """``this lap`` when a report is about the lap being driven, else how far back it is."""
        back = self._lap_no - lap
        if back <= 0:
            return "this lap"
        return "1 lap back" if back == 1 else f"{back} laps back"

    def _lap_phrase(self, lap: int) -> str:
        """The lap a report belongs to, for the message, when it is not the one being driven."""
        back = self._lap_no - lap
        if back <= 0:
            return ""
        return " in the previous lap" if back == 1 else " in an earlier lap"

    def _pos_at(self, at: float) -> tuple[float, bool, int] | None:
        """The car when the game wrote a report at ``at``: (position, in the pits, lap).

        None when ``at`` is older than the kept history - guessing from the current position would
        drop the wrong sector, which is worse than saying nothing.
        """
        s = self._last
        if s is not None and at >= s.t:
            return min(max(s.pos, 0.0), 0.99999), s.in_pit, self._lap_no
        for ts, pos, in_pit, lap in reversed(self._history):
            if ts <= at:
                return pos, in_pit, lap
        return None

    def _prune_lap_runs(self) -> None:
        """Forget the stored-run records of laps too old for a late cut to still reach.

        ``_invalid_sectors`` and ``_lap_notes`` are not pruned with them: they are a few small
        entries per lap, and keeping them means a log line read again (after a restart) is still
        recognised as one already acted on, and a late cut for a sector that was already out stays
        quiet, even once the run it took back is long gone.
        """
        oldest = self._lap_no - _RUNS_KEPT_LAPS + 1
        for key in [k for k in self._lap_runs if k[0] < oldest]:
            del self._lap_runs[key]

    def _drop_text(self, where: float, took_back: bool) -> str:
        """The sector a dropped spot fell in, and what happened to its run: "S2 won't count"."""
        outcome = "had its stored run taken back" if took_back else "won't count"
        return f"S{self._sector_of(where) + 1} {outcome}"

    def _infraction_pos(self, pos: float) -> float:
        """The lap position a report arriving at ``pos`` is really about.

        The game only reports a cut once the driver has failed to give the time back within its
        give-back window, so the cut happened ``cut_give_back_m`` of track behind the report.
        """
        back = self._settings.cut_give_back_m / max(self._length_m, 1.0)
        return (pos - back) % 1.0

    def _infraction_lap(self, pos: float, in_pit: bool) -> int:
        """The lap a cut reported at ``pos`` happened in.

        Same reasoning as :meth:`_infraction_pos`: a report closer to the line than the give-back
        distance is about a cut in the lap that has just ended, and taking it out of this lap's
        sector of that number would take the wrong run and grey the wrong colour.
        """
        if in_pit:
            return self._lap_no
        back = self._settings.cut_give_back_m / max(self._length_m, 1.0)
        return self._lap_no - 1 if pos - back < 0.0 else self._lap_no

    def _attribute(self, reason: str, where: float, lap: int) -> bool | None:
        """Make the sector of ``lap`` at ``where`` not count.

        Returns True when a stored run was taken back, False when the sector had none, and None
        when the game had already invalidated that ``(lap, sector)``: the signals overlap, so this
        is what keeps one cut from dropping two sectors or being announced twice.

        The sector may still be in progress (the pass is flagged) or already closed (its stored run
        is removed, since the game reported the cut too late to stop it being saved). A closed
        sector is shown as not counted either way, even when it had no run to take back.

        ``_status`` only holds one lap's colours: the lap being driven, after its first sector has
        closed, and the previous lap's until then. A cut is dropped on the lap it belongs to, so a
        late one for a lap whose colours are already gone touches no sector of the current lap.
        """
        idx = self._sector_of(where)
        key = (lap, idx)
        if key in self._invalid_sectors:
            return None
        self._invalid_sectors.add(key)
        if lap == self._lap_no and idx == self._sector:
            self._flag(reason)
        if lap == self._status_lap and 0 <= idx < len(self._status):
            self._status[idx] = SectorStatus.PENDING
        return self._drop_run(lap, idx)

    def _drop_run(self, lap: int, idx: int) -> bool:
        """Take back the run ``lap`` stored for sector ``idx``; True if there was one to take.

        Both the stored run and the run it displaced when it was kept are undone, as the top-runs
        list has already dropped the latter. The entry is keyed by lap, so a cut the game reports a
        lap late cannot take back the run a later lap has stored for the same sector.
        """
        entry = self._lap_runs.pop((lap, idx), None)
        if entry is None or self._data is None:
            return False
        run, previous = entry
        # Remove exactly the run this cut put in, and put back whatever it displaced. The whole
        # list cannot just be restored: a later lap may have stored a run of its own in this sector
        # since, and that one is clean and must stay. Runs are matched by identity, since two laps
        # can hold runs of equal value; the value is a fallback for data reloaded from disk.
        current = list(self._data.sectors[idx])
        kept = [r for r in current if r is not run]
        if len(kept) == len(current):
            for pos, other in enumerate(current):
                if other == run:
                    kept = [*current[:pos], *current[pos + 1 :]]
                    break
        for r in previous:
            if not any(r is k for k in kept):
                kept.append(r)
        self._data.sectors[idx] = sorted(kept, key=lambda r: r.t)[: self._settings.top_runs]
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
        """Sector lines for this track + car: the game's own, or the equal splits.

        Whether they are the game's own because this entry learned them, because another car
        did (:meth:`TrackStore.share_lines`), or because neither has yet, is settled before here.
        """
        data = self._data
        assert data is not None
        self._splits = {}
        self._lines_laps = 0
        fresh = data.boundaries is None and not data.total_runs()
        # A fresh entry waits for the game's own splits: the lines are the track's, so only a
        # track that no car has learned yet has to. An entry with runs keeps the lines it was
        # timed on, since moving those would re-file every stored run.
        self._learning_lines = bool(fresh and self._settings.use_game_log)
        self._bounds = full_bounds(self._n, data.boundaries)

    def _lines_watch(self) -> None:
        """Give up on the game's splits after a few laps, rather than counting nothing for ever."""
        if not self._learning_lines:
            return
        self._lines_laps += 1
        if self._lines_laps < _LINES_WAIT_LAPS:
            return
        self._learning_lines = False
        # The equal splits are the lines for good now, so the passes dropped on them were timed
        # between exactly these lines after all: store them rather than lose the first laps.
        changed = False
        for entry in self._lines_lost:
            changed = self._store_late(entry, round(entry.end - entry.run.t0, 3)) or changed
        self._lines_lost.clear()
        if changed and self._data is not None:
            self._rebuild_zones()
            self._store.save(self._data)
        self._on_message(
            f"The game's log brought no sector splits in {_LINES_WAIT_LAPS} laps: using equal "
            "sector lines. This build may not write them, or 'Follow the game's log' may be off "
            "in Settings > App."
        )

    def report_split(self, index: int, at: float) -> None:
        """The game's log reported a sector split; learn the line it crossed.

        ``index`` is the game's sector index: 0 ends the first sector, 1 the second, and 2 is the
        start/finish line (already 0.0, so it teaches nothing). ``at`` is when the game wrote the
        line, and the car's position then comes from the same history a late cut is attributed from.

        Both lines have to come from the *same lap*, and land in the roughly equal thirds the game
        uses, which keeps a reset or a teleport between them from placing a line. A split the game
        wrote on an out-lap is no worse than any other: it is the car's own position, and the lines
        belong to the track.
        """
        data = self._data
        if data is None or index not in (0, 1):
            return
        if data.boundaries is not None:
            return  # already learned: the lines stay where they are
        if data.total_runs():
            # A stored run is timed between two lines, so moving them would silently re-file every
            # sector. Learning only ever happens on a fresh entry, before any run is saved;
            # deleting the track's data is what learns the lines again.
            return
        if not self._settings.use_game_log:
            return
        found = self._pos_at(at)
        if found is None:
            log.debug("splits: index %d written at %.3f is older than the kept history", index, at)
            return
        pos, in_pit, lap = found
        if in_pit or not _split_position_ok(index, pos):
            log.debug(
                "splits: index %d at %.1f%% of the lap is not a sector line (in pit=%s, lap %d)",
                index,
                pos * 100.0,
                in_pit,
                lap,
            )
            return
        known = self._splits.get(index)
        if known is not None and known[2] > at:
            return  # an older, stale split (the out-lap one): keep the newer
        self._splits[index] = (pos, lap, at)
        log.debug(
            "splits: index %d crosses at %.1f%% of the lap (lap %d, read %.1f s later)",
            index,
            pos * 100.0,
            lap,
            (self._last.t - at) if self._last else 0.0,
        )
        first, second = self._splits.get(0), self._splits.get(1)
        if first is None or second is None or first[1] != second[1]:
            return  # need both lines of one lap
        if not (0.05 <= first[0] < second[0] <= 0.95):
            log.debug(
                "splits: %.1f%% / %.1f%% are not usable sector lines",
                first[0] * 100,
                second[0] * 100,
            )
            return
        self._learn_lines(first[0], second[0])

    def _learn_lines(self, first: float, second: float) -> None:
        """Adopt the game's two sector lines (both found on one lap) and use them from here on."""
        data = self._data
        if data is None:
            return
        data.boundaries = [first, second]
        self._bounds = full_bounds(self._n, data.boundaries)
        self._learning_lines = False
        self._store.save(data)
        self._rebuild_zones()
        self._status = [SectorStatus.PENDING] * self._n
        self._status_lap = self._lap_no
        # The app was drawing on stand-in equal splits, not the game's, and they have just changed:
        # the sector in progress is only still good if it began on a line both layouts share - the
        # start/finish line, where the read lands, right after the car crossed it, since the game
        # buffers its log. Such a sector started and ends on the game's own lines, so it is moved
        # onto them and counts. Started anywhere else, the samples still say when the car crossed
        # the game's line, so it is re-timed from there (see _reanchor).
        run, pos, t = (
            self._pass,
            self._last.pos if self._last else 0.0,
            self._last.t if self._last else 0.0,
        )
        if run is not None:
            if any(abs(run.start_pos - line) < _LINE_MATCH for line in self._bounds):
                self._sector = self._sector_of(run.start_pos)
                # It was flagged for being driven while the lines were unknown; they are known now.
                self._unflag("finding the sector lines")
            else:
                self._reanchor(run, pos, t)
        if self._settings.learning_enabled:
            self._retime_lost_sectors()
        else:
            self._lines_lost.clear()
        self._on_message(
            f"The game's sector lines: S1 ends at {first:.1%}, S2 at {second:.1%} of the lap "
            f"({self._length_m * first:.0f} m / {self._length_m * second:.0f} m)"
        )

    def _reanchor(self, run: _Pass, pos: float, t: float) -> None:
        """Move the pass in progress onto the game's line the sector really began on.

        It began on one of the stand-in equal splits, which has just moved. The samples still say
        when the car crossed the game's line for the sector it is in, so the pass is re-timed from
        there; its onsets, cleanliness and pause state carry over. Only when that crossing is gone
        from the history (a reset, or a sector longer than it) is the sector lost, and it says why
        rather than blaming the pit lane or a reset for it.
        """
        idx = self._sector_of(pos)
        start = self._crossing_time(self._lap_no, self._bounds[idx])
        if start is None or start > t:
            self._keep_onsets(run)  # the sector is lost, but the driver's braking points are not
            self._restart_pass(idx, t, pos)
            self._flag("the lines were learned mid-sector")
            return
        reasons = run.flagged - _LINES_REASONS
        self._sector = idx
        self._pass = _Pass(
            start,
            clean=run.clean,
            start_pos=self._bounds[idx],
            coverage=(pos - self._bounds[idx]) % 1.0,
            onsets=[o for o in run.onsets if self._sector_of(o) == idx],
            paused=run.paused,
            flagged=set(reasons),
        )

    def _retime_lost_sectors(self) -> None:
        """Time the sectors that closed before the game's lines arrived, from the samples.

        The game buffers its log, so the lines can turn up a lap or more after the sectors that
        needed them had closed. Their times were thrown away because they had been measured from
        the stand-in equal splits; now that the real lines are known, the samples still say when
        the car crossed them, so those sectors are timed and stored like any other. A sector the
        game took out, and any older than the kept history, stay dropped.
        """
        data = self._data
        if data is None:
            return
        now = self._last.t if self._last else 0.0
        lost = [x for x in self._lines_lost if x.end >= now - _HISTORY_S]
        self._lines_lost.clear()
        changed = False
        for entry in lost:
            start = self._crossing_time(entry.lap, self._bounds[entry.sector])
            end = self._crossing_time(entry.lap, self._bounds[entry.sector + 1])
            if start is None or end is None or not 0.0 < end - start < _HISTORY_S:
                continue
            changed = self._store_late(entry, round(end - start, 3)) or changed
        if changed:
            self._rebuild_zones()
            self._store.save(data)

    def _store_late(self, entry: _LostPass, duration: float) -> bool:
        """Store and report a sector timed after the fact; True when there was anything to save.

        ``duration`` comes either from the samples around the game's own lines (they arrived late)
        or from the pass itself (no lines ever arrived, so the equal splits it was timed on are the
        lines for good: see :meth:`_lines_watch`). A sector the game took out is never stored.
        """
        data = self._data
        if data is None or (entry.lap, entry.sector) in self._invalid_sectors:
            return False
        idx = entry.sector
        onsets = [p for p in entry.run.onsets if self._sector_of(p) == idx]
        runs = data.sectors[idx]
        previous_best = min((r.t for r in runs), default=None)
        stored = SectorRun(duration, onsets)
        kept = sorted([*runs, stored], key=lambda r: r.t)[: self._settings.top_runs]
        accepted = any(r is stored for r in kept)
        if accepted:
            data.sectors[idx] = kept
            self._lap_runs[(entry.lap, idx)] = (stored, runs)
        status = (
            SectorStatus.BEST
            if kept[0] is stored
            else SectorStatus.GOOD
            if accepted
            else SectorStatus.SLOWER
        )
        if entry.lap == self._status_lap and 0 <= idx < len(self._status):
            self._status[idx] = status
        changed = self._forget_early(entry.run.onsets) or accepted
        log.debug(
            "lines: S%d of lap %d timed after the fact: %.2f s (%s)",
            idx + 1,
            entry.lap,
            duration,
            "kept" if accepted else "not kept",
        )
        self._report(
            SectorResult(
                idx,
                duration,
                accepted,
                kept[0].t,
                "kept" if accepted else "not kept",
                len(onsets),
                status,
                previous_best,
            )
        )
        return changed

    def _forget_early(self, onsets: list[float]) -> bool:
        """Drop the stand-in vote a re-timed pass left; its timed run carries those onsets now."""
        data = self._data
        if data is None:
            return False
        for i in range(len(data.early_onsets) - 1, -1, -1):
            if data.early_onsets[i] == onsets:
                del data.early_onsets[i]
                return True
        return False

    def _crossing_time(self, lap: int, line: float) -> float | None:
        """When the car crossed ``line`` during ``lap``, interpolated between two samples.

        ``line`` is a lap fraction: 0.0 starts the lap and 1.0 ends it (and starts the next one).
        None when that crossing is no longer in the kept history: guessing would file a run under
        a time the car never drove.
        """
        if line <= 0.0:
            return self._lap_start(lap)
        if line >= 1.0:
            return self._lap_start(lap + 1)
        previous: tuple[float, float, int] | None = None  # t, pos, lap
        for t, pos, _in_pit, n in self._history:
            if (
                n == lap
                and previous is not None
                and previous[2] == lap
                and previous[1] < line <= pos
            ):
                span = pos - previous[1]
                if span > 0.0:
                    return previous[0] + (t - previous[0]) * ((line - previous[1]) / span)
                return t
            previous = (t, pos, n)
        return None

    def _lap_start(self, lap: int) -> float | None:
        """When the car crossed the line that starts ``lap``, from the samples around the wrap.

        The history records the lap a sample was taken in, so the sample that lands just after the
        line still carries the old number: the crossing is the wrap (a large drop in position) in
        the sample or two before the first one of ``lap``. None when the history now begins after
        it, so a lap whose start it no longer holds is not timed from a guess.
        """
        history = self._history
        first = next((i for i, entry in enumerate(history) if entry[3] == lap), None)
        if first is None:
            return None
        for j in (first, first - 1, first - 2):
            if j < 1:
                continue
            high, low = history[j - 1], history[j]
            if high[1] > 0.5 and low[1] < 0.05:  # the start/finish line between these two
                span = (1.0 - high[1]) + low[1]
                if span > 0.0:
                    return high[0] + (low[0] - high[0]) * ((1.0 - high[1]) / span)
        return None

    def _restart_pass(self, sector: int, t: float, pos: float) -> None:
        self._sector, self._pass, self._last_closed = (
            sector,
            _Pass(t, clean=False, start_pos=pos),
            None,
        )
        self._fired_warn.clear()
        self._fired_here.clear()

    def _report(self, result: SectorResult) -> None:
        self._last_result = result
        self._last_result_t = self._last.t if self._last else 0.0
        self._on_sector(result)
        self._on_message(result.describe())

    def _report_dropped(self, idx: int, note: str) -> None:
        """Report a sector that did not count, remembering why for a cut reported later."""
        self._lap_notes[(self._lap_no, idx)] = note
        self._report(SectorResult(idx, None, False, None, note))

    def _already_out(self, lap: int, idx: int) -> bool:
        """Did this sector already fail to count for a reason a cut report adds nothing to?

        That is a warm-up lap, the sector lines still being found, or a sector already reported as
        not counted (a reset or a pit stop makes it one when it closes). The track-limit signal
        still records the invalidation, but announcing it again would only repeat the result the
        driver already has.
        """
        if lap == self._lap_no and idx == self._sector and self._pass is not None:
            if self._pass.flagged:
                return True
            return self._settings.learning_enabled and self._pass.paused
        return self._lap_notes.get((lap, idx), "").startswith("not counted")

    def _close_sector(self, t: float) -> None:
        run, idx, data = self._pass, self._sector, self._data
        self._last_closed = None
        # this run is being replaced; only what we store now counts (this lap's, not a late cut's
        # entry for an earlier lap of the same sector number)
        self._lap_runs.pop((self._lap_no, idx), None)
        if run is None or data is None:
            return
        learning = self._settings.learning_enabled
        if idx == 0:  # a new lap's first sector is done: clear last lap's colours
            self._status = [SectorStatus.PENDING] * self._n
            self._status_lap = self._lap_no
        if run.flagged:  # a named reason beats the catch-all, even if the pass is also unclean
            self._keep_onsets(run)  # for the lines alone, the braking points are still good
            self._hold_lost(run, idx, t)  # ... and its time can still be recovered
            self._report_dropped(idx, f"not counted · {_note(run.flagged)}")
            return
        if not run.clean:
            self._report_dropped(idx, "not counted · pit, reset or partial")
            return
        if learning and run.paused:
            self._report_dropped(idx, "not counted · learning was paused")
            return
        width = self._bounds[idx + 1] - self._bounds[idx]
        if run.coverage < _COVERAGE_REQUIRED * width:
            share = run.coverage / width
            self._report_dropped(idx, f"not counted · {share:.0%} covered")
            return

        was_ref = learning and self._using_ref(idx)
        previous = list(data.sectors[idx])  # so a late cut report can put it back
        previous_best = min((r.t for r in previous), default=None)
        stored = SectorRun(round(t - run.t0, 3), list(run.onsets))
        kept = sorted([*previous, stored], key=lambda r: r.t)[: self._settings.top_runs]
        accepted = any(r is stored for r in kept)
        if kept[0] is stored:
            self._status[idx] = SectorStatus.BEST
        elif accepted:
            self._status[idx] = SectorStatus.GOOD
        else:
            self._status[idx] = SectorStatus.SLOWER

        if learning:
            data.sectors[idx] = kept
            if accepted:
                self._last_closed = (idx, stored)
                self._lap_runs[(self._lap_no, idx)] = (stored, previous)
                self._rebuild_zones()
                self._store.save(data)
        # with learning off the colours still show how the sector compared, but nothing is stored
        note = ("kept" if learning else "would be kept") if accepted else "not kept"
        status = self._status[idx]
        self._report(
            SectorResult(
                idx, stored.t, accepted, kept[0].t, note, len(stored.onsets), status, previous_best
            )
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

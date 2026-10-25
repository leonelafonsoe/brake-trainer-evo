"""Braking-point learning engine.

Pure logic: it consumes :class:`Sample` objects one at a time and reports cues and sector
results through callbacks. The only I/O is the injected :class:`TrackStore`.

Sector lines are the game's own: every lap is scored in three sectors and the game writes each
split to its log, so the two inner lines are learned from there (see
:meth:`BrakeEngine.report_split`) rather than invented here.

The engine is split across mixins that share nothing but ``self``: session and storage here,
sector passes in :mod:`.passes`, the sector lines in :mod:`.lines`, braking zones and track limits
in :mod:`.limits`, and braking cues in :mod:`.cues`. Every mixin sees :class:`BrakeEngine` only
for type checking, so the imports stay acyclic.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from ..config import Settings
from ..models import (
    CueKind,
    Sample,
    SectorResult,
    SectorRun,
    SectorStatus,
    Snapshot,
    TrackData,
)
from ..storage import DataEdit, TrackStore
from ..timeline import (
    JUMP_LAP,
    HistoryPoint,
    PositionTimeline,
    clamp_pos,
    crossing_between,
    wrap_delta,
)
from .constants import _HISTORY_S, DEFAULT_LENGTH_M, N_SECTORS
from .cues import CuesMixin, _BrakeEvent
from .limits import LimitsMixin
from .lines import LinesMixin
from .passes import PassesMixin, _LapRun, _LostPass, _Pass


class BrakeEngine(PassesMixin, LinesMixin, LimitsMixin, CuesMixin):
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
        self._pending_settings: deque[Settings] = deque()  # settings requested from the UI thread

        self._key: tuple[str, str] | None = None
        self._n = 0
        self._length_m = DEFAULT_LENGTH_M
        self._data: TrackData | None = None
        self._ref: TrackData | None = None
        self._zones: list[float] = []
        self._ref_zones: list[float] = []  # braking points borrowed from another car
        self._last: Sample | None = None
        self._last_result: SectorResult | None = None
        self._last_result_t = 0.0
        self._late_cut = ""  # a cut reported for a lap the sector bar no longer shows
        self._late_cut_t = 0.0
        self._storage_warning = ""  # a learned-data file that could not be read
        self._save_warning = ""  # a learned-data write that failed and has not succeeded since
        self._bounds: list[float] = []
        # The game's sector lines, still being learned from its split lines: while this is up the
        # laps are not counted, since a run timed between lines that then move would be filed wrong.
        self._learning_lines = False
        self._lines_laps = 0  # laps driven while waiting for the log to bring a split
        # Splits seen (index -> (position, lap, written at)) until both lines of one lap are in.
        self._splits: dict[int, tuple[float, int, float]] = {}
        self._lap_valid: bool | None = None  # None until the first sample tells us
        self._lap_no: int = 0  # counted up at every line crossing, so a late cut knows its own lap
        # The lap whose colours _status holds: the last one, until S1 ends.
        self._status_lap: int = 0
        self._lap_saw_off = False  # an off-track this lap, so a bare-cut drop is not it
        self._lap_warned: bool = False  # the cut warning was already given for this lap
        self._cut_active: bool = False  # the game's race-cut signal is up right now
        self._cut_gained: int = 0  # the last race-cut gain it reported, for spotting a new cut
        # Its give-back distance, which grows again when a new cut starts.
        self._cut_deadline: int = 0
        self._timeline = PositionTimeline(keep_s=_HISTORY_S)
        # Recently seen, per lap and sector: the run, what it displaced, and when it closed. A cut
        # the game reports a lap late can then be taken back cleanly without touching the run a
        # later lap stored for that sector.
        self._lap_runs: dict[tuple[int, int], _LapRun] = {}
        self._lines_lost: list[_LostPass] = []  # sectors the lines arrived too late for (yet)
        self._invalid_sectors: set[tuple[int, int]] = set()  # (lap, sector) the game invalidated
        # (lap, sector) -> why it did not count, for sectors already out for another reason. A cut
        # reported later for one of them changes nothing, so its message is not repeated.
        self._lap_notes: dict[tuple[int, int], str] = {}
        # The previous sample's race-cut state, for the verbose log.
        self._prev_cut_active: bool = False
        self._prev_cut_gained: int = 0
        self._prev_timing_invalid: bool = False
        self._laps_done = 0  # laps completed since leaving the pits / session start
        self._status: list[SectorStatus] = []
        self._prev_pos: float | None = None
        self._prev_t: float | None = None
        self._sector: int = 0
        self._pass: _Pass | None = None
        self._last_closed: tuple[int, SectorRun] | None = None
        self._fired_warn: set[float] = set()
        self._fired_here: set[float] = set()
        self._braking: bool = False
        self._event: _BrakeEvent | None = None

    # ------------------------------------------------------------------ public API

    @property
    def settings(self) -> Settings:
        return self._settings

    def apply_settings(self, settings: Settings) -> None:
        """Swap in new settings and apply the ones that change session state.

        Only the thread that runs :meth:`update` may call this. The UI queues a change with
        :meth:`queue_settings` instead, so it cannot land between a sample's own reads.

        Most settings are read on every sample and need no work here. The exceptions are the ones
        that decide what is stored: a new reference car is looked up again, a smaller run count
        trims what is kept, and turning the game log on or off starts or settles the wait for its
        sector lines. Zones are rebuilt once, so a change shows up without waiting for a sample.
        """
        if settings == self._settings:
            return
        old, self._settings = self._settings, settings
        self._apply_settings_diff(old, settings)
        if self._data is not None:
            self._rebuild_zones()

    def _apply_settings_diff(self, old: Settings, new: Settings) -> None:
        """Apply the settings that are not simply read when they are needed."""
        if self._data is None:
            return
        if old.reference_car != new.reference_car:
            self._ref = self._store.find_reference(
                self._data.track, self._data.car, self._n, new.reference_car
            )
            self._announce_reference()
        if new.top_runs < old.top_runs:
            self._trim_runs(new.top_runs)
        if old.use_game_log != new.use_game_log:
            if new.use_game_log:
                self._start_line_learning()
            else:
                self._settle_lines(
                    "'Follow the game's log' was turned off: using equal sector lines."
                )

    def _trim_runs(self, keep: int) -> bool:
        """Keep only the fastest ``keep`` runs per sector after the setting was reduced."""
        if self._data is None:
            return False
        changed = False
        for i, runs in enumerate(self._data.sectors):
            if len(runs) > keep:
                self._data.sectors[i] = sorted(runs, key=lambda r: r.t)[:keep]
                changed = True
        if changed:
            self._save(self._data)
            self._on_message(
                f"Keeping the {keep} fastest runs per sector: slower stored runs were removed"
            )
        return changed

    def queue_settings(self, settings: Settings) -> None:
        """Ask for new settings. Safe from any thread; applied by :meth:`apply_pending` on the
        worker thread, before the next sample or tick."""
        self._pending_settings.append(settings)

    def reset_tracking(self) -> None:
        """Forget the in-progress sector, e.g. after telemetry was interrupted."""
        self._clear_tracking()

    def queue_edit(self, edit: DataEdit) -> None:
        """Ask for a change to the stored data. Safe from any thread; applied on the next
        :meth:`apply_pending` so it cannot race with the engine's own saves."""
        self._pending.append(edit)

    def apply_pending(self) -> bool:
        """Apply settings and data edits queued from the UI thread.

        Settings go first, so an edit that reloads the entry in use sees the current ones. If an
        edit touches that entry, it is reloaded from disk (otherwise the in-memory copy would be
        saved back and undo the deletion). Returns whether a data edit changed the store.
        """
        while self._pending_settings:
            self.apply_settings(self._pending_settings.popleft())
        changed = False
        while self._pending:
            edit = self._pending.popleft()
            result = self._store.apply(edit)
            changed = result.changed or changed
            if not result.ok:
                self._report_save_failure(result.detail)
            elif result.changed and (edit.track, edit.car) == self._key:
                # The file changed under the engine: reload it at the next sample. A no-op or a
                # failed edit must not throw away runs that are still only in memory.
                self._data, self._key = None, None
        if changed:
            self._on_data_changed()
        return changed

    def _save(self, data: TrackData) -> bool:
        """Write learned data, keeping a failed write visible until one succeeds again."""
        result = self._store.save(data)
        if result.ok:
            if self._save_warning:
                self._save_warning = ""
                self._on_message("Learned data can be saved again")
            return True
        self._report_save_failure(result.detail)
        return False

    def _report_save_failure(self, detail: str) -> None:
        """Say once that the store cannot be written; the status line keeps saying it."""
        if self._save_warning:
            return
        self._save_warning = "Could not save learned data · see the log"
        self._on_warning(f"Could not save learned data: {detail}")

    def flush(self) -> None:
        if self._data is not None:
            self._save(self._data)

    def update(self, s: Sample) -> None:
        self.apply_pending()
        if s.length_m:
            self._length_m = s.length_m
        self._ensure_session(s)
        self._last = s

        pos = clamp_pos(s.pos)
        sector = self._sector_of(pos)

        self._timeline.append(HistoryPoint(s.t, pos, s.speed_kmh, s.in_pit, self._lap_no))

        delta, jump = 0.0, False
        prev_pos, prev_t = self._prev_pos, self._prev_t
        prev_lap = self._lap_no
        if prev_pos is not None:
            delta = wrap_delta(pos - prev_pos)  # signed, wrap-safe
            jump = abs(delta) > JUMP_LAP
        self._prev_pos, self._prev_t = pos, s.t
        if self._pass is None or jump:  # start, reset or teleport
            self._restart_pass(sector, s.t, pos)
        elif sector != self._sector:
            if sector == (self._sector + 1) % self._n:  # crossed into the next sector
                crossed = crossing_between(prev_t, prev_pos, s.t, pos, self._bounds[sector])
                self._close_sector(crossed)
                start = self._bounds[sector]
                self._sector = sector
                self._pass = _Pass(
                    crossed, clean=True, start_pos=start, coverage=(pos - start) % 1.0
                )
                if sector == 0:
                    if not s.in_pit:
                        self._laps_done += 1  # crossed the line: one more lap completed
                    self._lap_no += 1  # a new lap: late cuts of the old one no longer mark it
                    self._prune_lap_runs()
                    self._fired_warn.clear()
                    self._fired_here.clear()
                    self._lap_saw_off = False
                    self._lap_warned = False
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
            self._check_track_limits(
                s, pos, None if jump or prev_pos is None else (prev_pos, prev_lap)
            )
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
            storage_warning=self._save_warning or self._storage_warning,
        )

    def _clear_tracking(self) -> None:
        self._prev_pos = None
        self._prev_t = None
        self._lap_valid = None
        self._lap_no = 0
        self._status_lap = 0
        self._late_cut = ""
        self._late_cut_t = 0.0
        self._lap_saw_off = False
        self._lap_warned = False
        self._cut_active = False
        self._cut_gained = 0
        self._cut_deadline = 0
        self._timeline.clear()
        self._lap_runs = {}
        self._lines_lost.clear()
        self._invalid_sectors.clear()
        self._lap_notes.clear()
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
            self._storage_warning = ""
            self._data = self._store.load(s.track, s.car, n)
            self._ref = self._store.find_reference(s.track, s.car, n, self._settings.reference_car)
            self._clear_tracking()
            lines_from = self._store.share_lines(self._data)
            self._note_storage_issues()
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
                self._announce_reference()

    def _announce_reference(self) -> None:
        """Say which car the braking points are borrowed from, and for which sectors."""
        if self._ref is None:
            return
        active = [f"S{i + 1}" for i in range(self._n) if self._using_ref(i)]
        if active:
            self._on_message(
                f"Using {self._ref.car} as a rough reference for {', '.join(active)} "
                "until you have your own runs"
            )

    def _note_storage_issues(self) -> None:
        """Log unsafe data files once and keep a short version for the status line."""
        issues = self._store.take_issues()
        if not issues:
            return
        for issue in issues:
            outcome = (
                f"moved to {issue.quarantine_path}"
                if issue.quarantine_path is not None
                else "read-only; it will not be overwritten"
            )
            self._on_warning(f"Learned data {issue.path.name}: {issue.detail} ({outcome})")
        first = issues[0]
        if first.quarantine_path is not None:
            self._storage_warning = f"Data file {first.path.stem} moved to quarantine"
        else:
            self._storage_warning = f"Data file {first.path.stem} is read-only"

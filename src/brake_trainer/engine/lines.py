"""The game's sector lines, learned from its split log, and the lines mixin."""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..models import DropReason, SectorResult, SectorRun, SectorStatus
from ..outcomes import LINES_REASONS, outcome_for_run, render_outcome
from ..timeline import CarAt, clamp_pos
from .constants import _HISTORY_S, _LINE_MATCH, _LINES_WAIT_LAPS
from .passes import _LapRun, _LostPass, _Pass, keep_fastest

if TYPE_CHECKING:
    from .engine import BrakeEngine

log = logging.getLogger("brake_trainer.engine")


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


class LinesMixin:
    # BrakeEngine inherits this mixin, so mypy's rule that an explicit self type must be a
    # supertype of its class does not hold: the annotations are right and only the check needs
    # the per-method ignore. The state below is owned by BrakeEngine; it is declared here with
    # the full type it can hold between samples.
    _splits: dict[int, tuple[float, int, float]]
    _pass: _Pass | None

    def _start_line_learning(self: BrakeEngine) -> None:  # type: ignore[misc]
        """Wait for the game's splits again, if this entry has nothing that would be re-filed."""
        data = self._data
        if data is None or data.boundaries is not None or data.total_runs():
            return
        self._learning_lines = True
        self._lines_laps = 0
        self._splits.clear()
        self._on_message("Waiting for the game's sector lines again")

    def _at_time(self: BrakeEngine, at: float) -> CarAt | None:  # type: ignore[misc]
        """The car at ``at``, from the sample history.

        The interpolation rules - including the fallbacks for a reset, a teleport and a
        start/finish wrap - live in :class:`~.timeline.PositionTimeline`; this is the engine's
        adapter, which supplies the car as it is known now for a time at or after the newest
        sample. ``None`` when ``at`` is older than the kept history.
        """
        return self._timeline.at(at, self._car_now())

    def _car_now(self: BrakeEngine) -> CarAt | None:  # type: ignore[misc]
        """The car as the engine knows it now, for a lookup at or after the newest sample."""
        s = self._last
        if s is None:
            return None
        return CarAt(s.t, clamp_pos(s.pos), s.speed_kmh, s.in_pit, self._lap_no)

    def _sector_of(self: BrakeEngine, pos: float) -> int:  # type: ignore[misc]
        return min(max(bisect_right(self._bounds, pos) - 1, 0), self._n - 1)

    def _progress(self: BrakeEngine, pos: float) -> float:  # type: ignore[misc]
        pos = min(max(pos, 0.0), 0.99999)
        k = self._sector_of(pos)
        lo, hi = self._bounds[k], self._bounds[k + 1]
        return min(max((pos - lo) / (hi - lo), 0.0), 1.0)

    def _setup_bounds(self: BrakeEngine) -> None:  # type: ignore[misc]
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

    def _lines_watch(self: BrakeEngine) -> None:  # type: ignore[misc]
        """Give up on the game's splits after a few laps, rather than counting nothing for ever."""
        if not self._learning_lines:
            return
        self._lines_laps += 1
        if self._lines_laps < _LINES_WAIT_LAPS:
            return
        if self._settle_lines(
            f"The game's log brought no sector splits in {_LINES_WAIT_LAPS} laps: using equal "
            "sector lines. This build may not write them, or 'Follow the game's log' may be off "
            "in Settings > App."
        ):
            self._rebuild_zones()

    def _settle_lines(self: BrakeEngine, message: str) -> bool:  # type: ignore[misc]
        """Stop waiting for the game's lines and keep the passes they were too late for.

        Returns whether stored runs changed, so the caller can rebuild the zones.
        """
        if not self._learning_lines:
            return False
        self._learning_lines = False
        # The sector in progress started on the equal splits, which are now final: it is timed
        # between exactly the lines it will close on, so the wait no longer keeps it from counting.
        self._unflag(DropReason.FINDING_LINES)
        # The equal splits are the lines for good now, so the passes dropped on them were timed
        # between exactly these lines after all: store them rather than lose the first laps.
        changed = False
        for entry in self._lines_lost:
            changed = self._store_late(entry, round(entry.end - entry.run.t0, 3)) or changed
        self._lines_lost.clear()
        if changed and self._data is not None:
            self._save(self._data)
        self._on_message(message)
        return changed

    def report_split(self: BrakeEngine, index: int, at: float) -> None:  # type: ignore[misc]
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
        if not self._settings.use_game_log:
            return
        if data.boundaries is not None:
            # Already learned: the lines stay where they are. The game's own split still says where
            # its line really is, so compare it with the learned one (verbose log only). Nothing is
            # decided here, so the history is not touched at all unless that log is being written.
            if log.isEnabledFor(logging.DEBUG):
                found = self._at_time(at)
                if found is None:
                    log.debug(
                        "splits: index %d written at %.3f is older than the kept history", index, at
                    )
                elif found.in_pit or not _split_position_ok(index, found.pos):
                    log.debug(
                        "splits: index %d at %.1f%% of the lap is not a sector line "
                        "(in pit=%s, lap %d)",
                        index,
                        found.pos * 100.0,
                        found.in_pit,
                        found.lap,
                    )
                else:
                    self._audit_split(index, found.lap, at, found)
            return
        if data.total_runs():
            # A stored run is timed between two lines, so moving them would silently re-file every
            # sector. Learning only ever happens on a fresh entry, before any run is saved;
            # deleting the track's data is what learns the lines again.
            return
        found = self._at_time(at)
        if found is None:
            log.debug("splits: index %d written at %.3f is older than the kept history", index, at)
            return
        pos, in_pit, lap = found.pos, found.in_pit, found.lap
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

    def _audit_split(self: BrakeEngine, index: int, lap: int, at: float, car: CarAt) -> None:  # type: ignore[misc]
        """Compare the game's line with the line the app learned, from the same split.

        On a later lap the game's split timestamp says when the car really crossed the line; the
        app's line says where the car was when that timestamp was first seen. If the two agree, the
        car reaches the learned position at the same moment. The difference is therefore the
        placement error: in seconds directly, and in metres from the speed at the line. A value
        within one telemetry frame is expected; a persistent larger one means the line, the clocks
        or the log's timestamp need a closer look. Verbose log only.
        """
        data = self._data
        if data is None or data.boundaries is None:
            return
        line = data.boundaries[index]
        app_t = self._crossing_time(lap, line)
        if app_t is None:
            log.debug(
                "splits: audit index %d (lap %d): no crossing of the learned line in the history",
                index,
                lap,
            )
            return
        delta_ms = (app_t - at) * 1000.0
        metres = (app_t - at) * car.speed_kmh / 3.6
        side = "after" if delta_ms >= 0 else "before"
        log.debug(
            "splits: audit index %d at %.1f%% (lap %d, %.0f km/h): the app's line was crossed "
            "%.1f ms / %.1f m %s the game's",
            index,
            line * 100.0,
            lap,
            car.speed_kmh,
            abs(delta_ms),
            abs(metres),
            side,
        )

    def _learn_lines(self: BrakeEngine, first: float, second: float) -> None:  # type: ignore[misc]
        """Adopt the game's two sector lines (both found on one lap) and use them from here on."""
        data = self._data
        if data is None:
            return
        data.boundaries = [first, second]
        self._bounds = full_bounds(self._n, data.boundaries)
        self._learning_lines = False
        self._save(data)
        self._rebuild_zones()
        self._status = [SectorStatus.PENDING] * self._n
        self._status_lap = self._lap_no
        # The app was drawing on stand-in equal splits, not the game's, and they have just changed:
        # the sector in progress is only still good if it began on a line both layouts share - the
        # start/finish line, where the read lands, right after the car crossed it, since the game
        # buffers its log - and the car is still in the sector that began there. Such a sector
        # started and ends on the game's own lines, so it is moved onto them and counts. Started
        # anywhere else - or already past the game's next line, because the buffered read arrived
        # after the car crossed it - the samples still say when the car crossed the game's line, so
        # it is re-timed from there (see _reanchor).
        run, pos, t = (
            self._pass,
            self._last.pos if self._last else 0.0,
            self._last.t if self._last else 0.0,
        )
        if run is not None:
            on_shared_line = any(abs(run.start_pos - line) < _LINE_MATCH for line in self._bounds)
            still_in_it = self._sector_of(pos) == self._sector_of(run.start_pos)
            if on_shared_line and still_in_it:
                self._sector = self._sector_of(run.start_pos)
                # It was flagged for being driven while the lines were unknown; they are known now.
                self._unflag(DropReason.FINDING_LINES)
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

    def _reanchor(self: BrakeEngine, run: _Pass, pos: float, t: float) -> None:  # type: ignore[misc]
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
            self._flag(DropReason.LINES_MOVED)
            return
        reasons = run.flagged - LINES_REASONS
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

    def _retime_lost_sectors(self: BrakeEngine) -> None:  # type: ignore[misc]
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
            self._save(data)

    def _store_late(self: BrakeEngine, entry: _LostPass, duration: float) -> bool:  # type: ignore[misc]
        """Store and report a sector timed after the fact; True when there was anything to save.

        ``duration`` comes either from the samples around the game's own lines (they arrived late)
        or from the pass itself (no lines ever arrived, so the equal splits it was timed on are the
        lines for good: see :meth:`_lines_watch`). A sector the game took out is never stored.
        """
        data = self._data
        if not self._settings.learning_enabled:
            # Pausing learning must freeze the data: a pass held while it was on is not a reason
            # to write once the driver has asked the app to stop changing anything.
            return False
        if data is None or (entry.lap, entry.sector) in self._invalid_sectors:
            return False
        idx = entry.sector
        onsets = [p for p in entry.run.onsets if self._sector_of(p) == idx]
        runs = data.sectors[idx]
        previous_best = min((r.t for r in runs), default=None)
        stored = SectorRun(duration, onsets)
        kept, accepted, status = keep_fastest(runs, stored, self._settings.top_runs)
        if accepted:
            data.sectors[idx] = kept
            self._lap_runs[(entry.lap, idx)] = _LapRun(stored, runs, entry.end)
        if entry.lap == self._status_lap and 0 <= idx < len(self._status):
            self._status[idx] = status
        changed = self._forget_early(entry.run.onsets) or accepted
        outcome = outcome_for_run(accepted, learning=True)
        log.debug(
            "lines: S%d of lap %d timed after the fact: %.2f s (%s)",
            idx + 1,
            entry.lap,
            duration,
            render_outcome(outcome),
        )
        self._report(
            SectorResult(
                idx,
                duration,
                accepted,
                kept[0].t,
                render_outcome(outcome),
                len(onsets),
                status,
                previous_best,
                outcome,
            )
        )
        return changed

    def _forget_early(self: BrakeEngine, onsets: list[float]) -> bool:  # type: ignore[misc]
        """Drop the stand-in vote a re-timed pass left; its timed run carries those onsets now."""
        data = self._data
        if data is None:
            return False
        for i in range(len(data.early_onsets) - 1, -1, -1):
            if data.early_onsets[i] == onsets:
                del data.early_onsets[i]
                return True
        return False

    def _crossing_time(self: BrakeEngine, lap: int, line: float) -> float | None:  # type: ignore[misc]
        """When the car crossed ``line`` during ``lap`` (see :meth:`PositionTimeline.crossing`)."""
        return self._timeline.crossing(lap, line)

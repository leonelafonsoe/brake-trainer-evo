"""Braking zones, the game's track-limit signals and their attribution."""

from __future__ import annotations

import logging
import statistics
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..models import DropReason, Sample, SectorRun, SectorStatus
from .constants import _CUT_WARNING, _HISTORY_S

if TYPE_CHECKING:
    from .engine import BrakeEngine

log = logging.getLogger("brake_trainer.engine")


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


def race_cut_active(gained_ms: int, deadline_m: int) -> bool:
    """Is the game currently holding a cut against the driver? Both fields are 0 when it is not."""
    return gained_ms > 0 or deadline_m > 0


class LimitsMixin:
    # BrakeEngine inherits this mixin, so mypy's rule that an explicit self type must be a
    # supertype of its class does not hold: the annotations are right and only the check needs
    # the per-method ignore. The state below is owned by BrakeEngine; it is declared here with
    # the full type it can hold between samples.
    _last_closed: tuple[int, SectorRun] | None

    def _using_ref(self: BrakeEngine, i: int) -> bool:  # type: ignore[misc]
        """Is sector ``i`` still using borrowed braking points?

        Borrowed points are matched by track position, so the other car's sector lines do not
        need to match ours.
        """
        if not self._ref_zones or not self._data:
            return False
        lo, hi = self._bounds[i], self._bounds[i + 1]
        borrowed = any(lo <= z < hi for z in self._ref_zones)
        return borrowed and len(self._data.sectors[i]) < self._settings.own_runs_to_replace_ref

    def _early_runs(self: BrakeEngine) -> list[list[SectorRun]]:  # type: ignore[misc]
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

    def _rebuild_zones(self: BrakeEngine) -> None:  # type: ignore[misc]
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

    def _check_track_limits(  # type: ignore[misc]
        self: BrakeEngine, s: Sample, pos: float, prev: tuple[float, int] | None = None
    ) -> None:
        """Track limits and other infractions, from the game's telemetry.

        The game's own signals, in the frames the app already reads:

        * ``is_valid_lap`` is a *one-shot* state: it drops when the game invalidates the lap and
          stays down until the lap ends, so on its own it can only mark one cut per lap. It is
          attributed at the position where it drops, which is where the game judged the cut;
        * the race-cut pair (time gained and the distance left to give it back) is filled in for
          every off-track, where the game publishes it.

        A second cut in an already-invalid lap comes from the game's log (see
        :meth:`report_infraction`), which the app follows for exactly that event.

        An infraction the game judges from something it does not expose (no cut in its log and no
        race cut) cannot be pinned to a sector; that is said out loud (a warning) rather than
        guessed at.

        The signals overlap: one cut can be seen by the race-cut pair, by the lap flag and in the
        log. Each is attributed to a ``(lap, sector)`` and only the first one to reach it acts, so
        the same cut never drops two sectors (nor says so twice), while two cuts in different
        sectors of one lap each drop their own.

        ``prev`` is the previous sample's position and lap, when the app has one and the car did
        not teleport into this one; the one-shot flag uses it to see a sector line in the frame.
        """
        if log.isEnabledFor(logging.DEBUG):  # verbose mode: trace the signals as they change
            self._trace_track_limits(s, pos)
        self._check_race_cut(s, pos)
        self._check_lap_flag(s, pos, prev)

    def _check_race_cut(self: BrakeEngine, s: Sample, pos: float) -> None:  # type: ignore[misc]
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
        if self._attribute(DropReason.OFF_TRACK, pos, self._lap_no) is None:
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

    def _check_lap_flag(  # type: ignore[misc]
        self: BrakeEngine, s: Sample, pos: float, prev: tuple[float, int] | None = None
    ) -> None:
        """The one-shot lap flag: drop the sector the infraction happened in.

        The flag drops where the game judged the cut, and the log notification for the same cut
        names the same spot, so the event's own position is the sector to drop - except in the
        frame that crosses a sector line, where the position has already moved on (see
        :meth:`_flag_attribution`).
        """
        if not self._settings.skip_invalid_sectors or s.lap_valid or self._lap_valid is False:
            return
        fresh = bool(self._lap_valid)  # a fresh drop, not the state the app found at start-up
        found = self._flag_attribution(pos, prev)
        if found is None:
            return
        where, lap = found
        idx = self._sector_of(where)
        # A pass that already will not count - a warm-up lap, the lines still being learned, or one
        # that began mid-sector - makes this drop a no-op. Say nothing rather than announce a loss
        # the driver has been told about already: the game invalidates an out-lap's opening sector
        # *because* it began in the pits, and the app would otherwise open a session with "S1 won't
        # count".
        run = self._pass if lap == self._lap_no and idx == self._sector else None
        already = self._already_out(lap, idx) or (run is not None and not run.clean)
        took_back = self._attribute(DropReason.LAP_INVALIDATED, where, lap)
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
        if lap != self._lap_no or self._lap_saw_off or self._lap_warned:
            return
        self._lap_warned = True
        if self._settings.use_game_log:
            # The log reports every cut - including this one, a few seconds later - so it is the
            # authority on the sector the cut happened in; only note the fallback, do not warn.
            log.debug("limits: lap flag dropped with no cut seen yet; the log may still explain it")
        else:
            self._on_warning(_CUT_WARNING)

    def _flag_attribution(  # type: ignore[misc]
        self: BrakeEngine, pos: float, prev: tuple[float, int] | None
    ) -> tuple[float, int] | None:
        """Where and on which lap a fresh one-shot flag belongs, or None to leave it to the log.

        The flag has no timestamp: the app only sees that it went down between the previous sample
        and this one. When that frame crossed a sector line, the position after the line is not
        evidence that the infraction happened there - at the start/finish line it would drop S1 of
        a lap the car has not driven yet. The game's log names the cut's own time, so with the log
        on the live flag defers to it rather than guessing a sector the log may attribute
        elsewhere. Without the log, the earlier sample is the safe choice: it is the sector the
        car was in when the flag went down.
        """
        if prev is None:
            return pos, self._lap_no
        prev_pos, prev_lap = prev
        crossed = prev_lap != self._lap_no or self._sector_of(prev_pos) != self._sector_of(pos)
        if not crossed:
            return pos, self._lap_no
        if self._settings.use_game_log:
            log.debug(
                "limits: lap flag fell in the frame that crossed a sector line at %.1f%%; "
                "the log will place it",
                pos * 100.0,
            )
            return None
        return prev_pos, prev_lap

    def report_infraction(self: BrakeEngine, reason: str, at: float) -> None:  # type: ignore[misc]
        """The game's log reported a cut; drop the sector it happened in.

        Called from the log tail (same thread as :meth:`update`). ``at`` is when the game wrote the
        line, which is where and when the cut was judged. The game buffers its log (a few KB,
        flushed when full), so a cut can be read seconds or a whole lap after it was judged, and a
        whole batch can arrive at once. Each is therefore attributed from the car's position
        *then*, and to the lap it happened in - never to the sector of the same number in the lap
        being driven now.

        One cut can also be seen live (the race-cut pair, the lap flag) and re-read when the game
        restarts its log: a ``(lap, sector)`` the app already invalidated is not dropped again.
        """
        s = self._last
        if s is None or self._pass is None or not self._settings.skip_invalid_sectors:
            return
        found = self._at_time(at)
        if found is None:
            log.debug(
                "limits: %s written at %.3f is older than the kept history (%.0f s): not used",
                reason,
                at,
                _HISTORY_S,
            )
            return
        pos, lap = found.pos, found.lap
        if lap == self._lap_no:  # a cut of the lap being driven: not a bare lap-flag drop
            self._lap_saw_off = True
        where = pos
        idx = self._sector_of(where)
        quiet = self._already_out(lap, idx)  # before _attribute flags this pass
        took_back = self._attribute(DropReason.OFF_TRACK, where, lap)
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
            "limits: %s written at %.3f (read %.1f s later, %s), car at %.1f%% (S%d), run %s",
            reason,
            at,
            s.t - at,
            self._laps_back(lap),
            pos * 100.0,
            idx + 1,
            "taken back" if took_back else "not stored",
        )
        self._on_message(self._report_text(reason, where, lap, took_back))

    def _report_text(  # type: ignore[misc]
        self: BrakeEngine, reason: str, where: float, lap: int, took_back: bool
    ) -> str:
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

    def _laps_back(self: BrakeEngine, lap: int) -> str:  # type: ignore[misc]
        """``this lap`` when a report is about the lap being driven, else how far back it is."""
        back = self._lap_no - lap
        if back <= 0:
            return "this lap"
        return "1 lap back" if back == 1 else f"{back} laps back"

    def _lap_phrase(self: BrakeEngine, lap: int) -> str:  # type: ignore[misc]
        """The lap a report belongs to, for the message, when it is not the one being driven."""
        back = self._lap_no - lap
        if back <= 0:
            return ""
        return " in the previous lap" if back == 1 else " in an earlier lap"

    def _drop_text(self: BrakeEngine, where: float, took_back: bool) -> str:  # type: ignore[misc]
        """The sector a dropped spot fell in, and what happened to its run: "S2 won't count"."""
        outcome = "had its stored run taken back" if took_back else "won't count"
        return f"S{self._sector_of(where) + 1} {outcome}"

    def _attribute(self: BrakeEngine, reason: DropReason, where: float, lap: int) -> bool | None:  # type: ignore[misc]
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

    def _drop_run(self: BrakeEngine, lap: int, idx: int) -> bool:  # type: ignore[misc]
        """Take back the run ``lap`` stored for sector ``idx``; True if there was one to take.

        Both the stored run and the run it displaced when it was kept are undone, as the top-runs
        list has already dropped the latter. The entry is keyed by lap, so a cut the game reports a
        lap late cannot take back the run a later lap has stored for the same sector.
        """
        entry = self._lap_runs.pop((lap, idx), None)
        if entry is None or self._data is None:
            return False
        run, previous = entry.run, entry.previous
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
        self._save(self._data)
        return True

    def _trace_track_limits(self: BrakeEngine, s: Sample, pos: float) -> None:  # type: ignore[misc]
        """Verbose log of the game's track-limit signals, only when one of them changes.

        This is the detail a report about a missed sector needs: what the game actually reported
        and when, with the position and sector. Off unless verbose logging is on.
        """
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
            log.debug(
                "limits: lap_valid %s -> %s at %.1f%% of the lap (S%d)",
                self._lap_valid,
                s.lap_valid,
                pos * 100.0,
                self._sector + 1,
            )

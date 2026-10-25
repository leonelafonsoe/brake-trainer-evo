"""Sector passes: the pass in progress, why it will not count, and closing it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..models import (
    DropReason,
    OutcomeKind,
    SectorOutcome,
    SectorResult,
    SectorRun,
    SectorStatus,
)
from ..outcomes import (
    LINES_REASONS,
    NOT_COUNTING_ANYWAY,
    PASS_FLAGS,
    primary,
    render_outcome,
)
from .constants import _COVERAGE_REQUIRED, _HISTORY_S

if TYPE_CHECKING:
    from .engine import BrakeEngine


@dataclass(slots=True)
class _Pass:
    """A sector pass in progress."""

    t0: float
    clean: bool
    start_pos: float = 0.0  # where it began, so a changed sector line can tell if it is still valid
    coverage: float = 0.0
    onsets: list[float] = field(default_factory=list)
    paused: bool = False  # learning was off during part of this pass
    flagged: set[DropReason] = field(default_factory=set)  # reasons this pass must not count


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
class _LapRun:
    """A stored run, what it displaced, and when it closed.

    Kept for a while so a cut the game reports late can be taken back cleanly without touching
    the run a later lap stored for the same sector. ``at`` is what the retention window is pruned
    against, so a record expires with the samples a report would be attributed from.
    """

    run: SectorRun
    previous: list[SectorRun]
    at: float


class PassesMixin:
    # BrakeEngine inherits this mixin, so mypy's rule that an explicit self type must be a
    # supertype of its class does not hold: the annotations are right and only the check needs
    # the per-method ignore. The state below is owned by BrakeEngine; it is declared here with
    # the full type it can hold between samples.
    _pass: _Pass | None
    _last_closed: tuple[int, SectorRun] | None
    _last_result: SectorResult | None

    def _pass_flag(self: BrakeEngine) -> DropReason | None:  # type: ignore[misc]
        """The most important reason the sector in progress will not count, if any."""
        if self._pass is None:
            return None
        if self._pass.flagged.intersection(NOT_COUNTING_ANYWAY):
            return None
        return next((flag for flag in PASS_FLAGS if flag in self._pass.flagged), None)

    def _keep_onsets(self: BrakeEngine, run: _Pass | None) -> None:  # type: ignore[misc]
        """Keep where the driver braked in a pass that only the sector lines kept from counting.

        A pass flagged for the lines alone is a pass the driver drove normally through the sector:
        only the app's lack of knowledge of where the lines were (or the lines moving under it) made
        it uncountable. Their times cannot be trusted, but their braking points are positions on the
        track, and on a new track they are all the cues there are until a sector has been timed -
        which, with the game's log buffered, is a lap or two after the driver would like them.
        """
        if (
            self._data is None
            or not self._settings.learning_enabled
            or run is None
            or not run.onsets
            or not run.clean
            or run.paused
            or not self._lines_only(run.flagged)
        ):
            return
        self._data.early_onsets.append(list(run.onsets))
        self._save(self._data)
        self._rebuild_zones()

    @staticmethod
    def _lines_only(reasons: set[DropReason]) -> bool:
        """Were the sector lines the only thing keeping this pass from counting?"""
        return bool(reasons) and reasons <= LINES_REASONS

    def _hold_lost(self: BrakeEngine, run: _Pass, sector: int, end: float) -> None:  # type: ignore[misc]
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

    def _flag(self: BrakeEngine, reason: DropReason) -> None:  # type: ignore[misc]
        """Add a reason the pass in progress must not count (once per reason)."""
        if self._pass is not None:
            self._pass.flagged.add(reason)

    def _unflag(self: BrakeEngine, reason: DropReason) -> None:  # type: ignore[misc]
        """Take a reason back: it no longer applies to the pass in progress."""
        if self._pass is not None:
            self._pass.flagged.discard(reason)

    def _prune_lap_runs(self: BrakeEngine) -> None:  # type: ignore[misc]
        """Forget the stored-run records older than the samples a late cut can reach.

        A report is attributed from the sample history, so once a run closed before that history
        begins no report can reach it. Pruning the two against the same window keeps them in
        step: the records do not outlive the samples that would identify them.

        ``_invalid_sectors`` and ``_lap_notes`` are not pruned with them: they are a few small
        entries per lap, and keeping them means a log line read again (after a restart) is still
        recognised as one already acted on, and a late cut for a sector that was already out stays
        quiet, even once the run it took back is long gone.
        """
        now = self._last.t if self._last is not None else None
        if now is None:
            return
        cutoff = now - _HISTORY_S
        for key in [k for k, entry in self._lap_runs.items() if entry.at < cutoff]:
            del self._lap_runs[key]

    def _restart_pass(self: BrakeEngine, sector: int, t: float, pos: float) -> None:  # type: ignore[misc]
        self._sector, self._pass, self._last_closed = (
            sector,
            _Pass(t, clean=False, start_pos=pos),
            None,
        )
        self._fired_warn.clear()
        self._fired_here.clear()

    def _report(self: BrakeEngine, result: SectorResult) -> None:  # type: ignore[misc]
        self._last_result = result
        self._last_result_t = self._last.t if self._last else 0.0
        self._on_sector(result)
        self._on_message(result.describe())

    def _report_dropped(self: BrakeEngine, idx: int, outcome: SectorOutcome) -> None:  # type: ignore[misc]
        """Report a sector that did not count, remembering why for a cut reported later."""
        self._lap_notes[(self._lap_no, idx)] = outcome
        self._report(SectorResult(idx, None, False, None, render_outcome(outcome), outcome=outcome))

    def _already_out(self: BrakeEngine, lap: int, idx: int) -> bool:  # type: ignore[misc]
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
        return (lap, idx) in self._lap_notes

    def _close_sector(self: BrakeEngine, t: float) -> None:  # type: ignore[misc]
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
            self._report_dropped(idx, SectorOutcome(OutcomeKind.DROPPED, primary(run.flagged)))
            return
        if not run.clean:
            self._report_dropped(
                idx, SectorOutcome(OutcomeKind.DROPPED, DropReason.PIT_RESET_PARTIAL)
            )
            return
        if learning and run.paused:
            self._report_dropped(idx, SectorOutcome(OutcomeKind.DROPPED, DropReason.PAUSED))
            return
        width = self._bounds[idx + 1] - self._bounds[idx]
        if run.coverage < _COVERAGE_REQUIRED * width:
            share = run.coverage / width
            self._report_dropped(
                idx, SectorOutcome(OutcomeKind.DROPPED, DropReason.COVERAGE, f"{share:.0%}")
            )
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
                self._lap_runs[(self._lap_no, idx)] = _LapRun(stored, previous, t)
                self._rebuild_zones()
                self._save(data)
        # with learning off the colours still show how the sector compared, but nothing is stored
        if not accepted:
            outcome = SectorOutcome(OutcomeKind.NOT_KEPT)
        elif learning:
            outcome = SectorOutcome(OutcomeKind.KEPT)
        else:
            outcome = SectorOutcome(OutcomeKind.WOULD_KEEP)
        status = self._status[idx]
        self._report(
            SectorResult(
                idx,
                stored.t,
                accepted,
                kept[0].t,
                render_outcome(outcome),
                len(stored.onsets),
                status,
                previous_best,
                outcome,
            )
        )
        if was_ref and not self._using_ref(idx):
            self._on_message(f"S{idx + 1}: now using your own braking points for this car")

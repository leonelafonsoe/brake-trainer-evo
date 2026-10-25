from __future__ import annotations

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import (
    DropReason,
    OutcomeKind,
    SectorOutcome,
    SectorResult,
    Snapshot,
)
from brake_trainer.outcomes import (
    LINES_REASONS,
    NOT_COUNTING_ANYWAY,
    PASS_FLAGS,
    PRIORITY,
    pass_flag_text,
    primary,
    render_outcome,
    render_reason,
)
from brake_trainer.ui import theme
from brake_trainer.ui.status import status_line

from .conftest import Driver

CORNERS = [0.20, 0.50, 0.80]

WORDS = {
    DropReason.WARM_UP: "warm-up lap",
    DropReason.FINDING_LINES: "finding the sector lines",
    DropReason.LINES_MOVED: "the lines were learned mid-sector",
    DropReason.PIT_RESET_PARTIAL: "pit, reset or partial",
    DropReason.PAUSED: "learning was paused",
    DropReason.COVERAGE: "42% covered",
    DropReason.OFF_TRACK: "off track",
    DropReason.LAP_INVALIDATED: "lap invalidated",
}


@pytest.mark.parametrize("reason", list(DropReason))
def test_every_reason_renders_its_phrase(reason):
    detail = "42%" if reason is DropReason.COVERAGE else ""
    assert render_reason(reason, detail) == WORDS[reason]


def test_primary_picks_the_documented_priority_regardless_of_set_order():
    # Every reason, and every suffix of the priority list, picks its first member.
    assert set(PRIORITY) == set(DropReason)
    for index, expected in enumerate(PRIORITY):
        assert primary(set(PRIORITY[index:])) is expected


def test_primary_rejects_an_empty_drop_and_falls_back_stably(monkeypatch):
    with pytest.raises(ValueError):
        primary(set())
    # Every real reason is in PRIORITY; with that list emptied, the fallback must still be stable.
    monkeypatch.setattr("brake_trainer.outcomes.PRIORITY", ())
    assert primary({DropReason.WARM_UP, DropReason.OFF_TRACK}) is DropReason.OFF_TRACK


def test_a_dropped_outcome_without_a_reason_still_renders_something():
    assert render_outcome(SectorOutcome(OutcomeKind.DROPPED)) == "not counted"


def test_combined_and_duplicate_flags_produce_one_note():
    outcome = SectorOutcome(
        OutcomeKind.DROPPED,
        primary({DropReason.OFF_TRACK, DropReason.WARM_UP, DropReason.WARM_UP}),
    )
    text = render_outcome(outcome)
    assert text == "not counted · warm-up lap"
    assert text.count("not counted") == 1


def test_quiet_is_true_only_for_a_dropped_warm_up_or_lines_pass():
    for reason in DropReason:
        assert SectorOutcome(OutcomeKind.DROPPED, reason).quiet is (
            reason in (DropReason.WARM_UP, DropReason.FINDING_LINES)
        )
    for kind in (OutcomeKind.KEPT, OutcomeKind.WOULD_KEEP, OutcomeKind.NOT_KEPT):
        assert not SectorOutcome(kind).quiet


def test_render_outcome_and_the_pass_flag_keep_the_existing_words():
    assert render_outcome(SectorOutcome(OutcomeKind.KEPT)) == "kept"
    assert render_outcome(SectorOutcome(OutcomeKind.WOULD_KEEP)) == "would be kept"
    assert render_outcome(SectorOutcome(OutcomeKind.NOT_KEPT)) == "not kept"
    assert render_outcome(SectorOutcome(OutcomeKind.DROPPED, DropReason.PAUSED)) == (
        "not counted · learning was paused"
    )
    assert pass_flag_text(None) == ""
    assert pass_flag_text(DropReason.LAP_INVALIDATED) == "lap invalidated"
    assert pass_flag_text(DropReason.OFF_TRACK) == "off track"


def test_the_reason_sets_stay_in_step_with_the_pass_logic():
    assert PASS_FLAGS == (DropReason.LAP_INVALIDATED, DropReason.OFF_TRACK)
    assert NOT_COUNTING_ANYWAY == (DropReason.WARM_UP, DropReason.FINDING_LINES)
    assert {DropReason.FINDING_LINES, DropReason.LINES_MOVED} == LINES_REASONS


def test_engine_results_carry_a_typed_outcome(store):
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1), store, on_sector=results.append
    )
    driver = Driver(engine)
    driver.lap(CORNERS)  # warm-up
    for _ in range(4):  # the equal splits settle after three laps
        driver.lap(CORNERS)

    assert results
    assert all(result.outcome is not None for result in results)
    outcomes = [result.outcome for result in results if result.outcome is not None]
    assert any(outcome.reason is DropReason.WARM_UP for outcome in outcomes)  # the warm-up lap
    assert any(
        outcome.kind in (OutcomeKind.KEPT, OutcomeKind.WOULD_KEEP, OutcomeKind.NOT_KEPT)
        for outcome in outcomes
    )
    for result in results:
        assert result.outcome is not None
        assert result.note == render_outcome(result.outcome)


def _snapshot(result: SectorResult) -> Snapshot:
    return Snapshot(sector=1, zones=(0.1,), last_result=result, last_result_age=1.0)


def test_status_uses_the_typed_outcome_before_the_note_text():
    # A quiet outcome is suppressed even when its note is not one of the old quiet phrases...
    quiet = SectorResult(
        1,
        None,
        False,
        None,
        "dropped for a reason the old status line did not know",
        outcome=SectorOutcome(OutcomeKind.DROPPED, DropReason.WARM_UP),
    )
    assert status_line(_snapshot(quiet), Settings(), True)[0] == "1 braking points"
    # ... and a result whose outcome is not quiet is shown, even if its note happens to match.
    loud = SectorResult(
        1,
        None,
        False,
        None,
        "not counted · warm-up lap",
        outcome=SectorOutcome(OutcomeKind.DROPPED, DropReason.OFF_TRACK),
    )
    assert status_line(_snapshot(loud), Settings(), True) == (
        "S2 not counted · warm-up lap",
        theme.AMBER,
    )


def test_a_hand_built_result_still_uses_the_note_fallback():
    warm = SectorResult(1, None, False, None, "not counted · finding the sector lines")
    assert status_line(_snapshot(warm), Settings(), True)[0] == "1 braking points"


def test_already_out_reads_the_remembered_outcome_not_its_text(store):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    # The map stores outcomes, not the driver-facing note: any dropped outcome is remembered,
    # whatever detail it carries.
    engine._lap_notes[(0, 2)] = SectorOutcome(OutcomeKind.DROPPED, DropReason.COVERAGE, "12.5%")
    assert engine._already_out(0, 2)
    assert not engine._already_out(0, 1)

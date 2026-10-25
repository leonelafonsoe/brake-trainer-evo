from __future__ import annotations

from brake_trainer.config import Settings
from brake_trainer.models import SectorResult, SectorStatus, Snapshot
from brake_trainer.ui import theme
from brake_trainer.ui.status import status_line

ST = Settings()


def snap(**kw) -> Snapshot:
    base = {"sector": 2, "zones": (0.1, 0.5)}
    return Snapshot(**{**base, **kw})


def result(status=SectorStatus.BEST, duration=18.01, best=None, note="kept", was=None):
    return SectorResult(1, duration, True, duration if best is None else best, note, 1, status, was)


def test_nothing_to_say_when_not_live():
    assert status_line(snap(), ST, live=False) is None


def test_a_storage_warning_outranks_the_normal_status():
    text = "Data file Monza__Car_A moved to quarantine"
    assert status_line(snap(storage_warning=text), ST, True) == (text, theme.RED)


def test_current_sector_that_will_not_count_has_top_priority():
    text, colour = status_line(snap(pass_flag="lap invalidated", warming_up=True), ST, True)
    assert text == "S3 won't count · lap invalidated" and colour == theme.RED


def test_paused_and_warm_up_states():
    assert status_line(snap(), Settings(learning_enabled=False), True)[0] == "Learning paused"
    assert status_line(snap(warming_up=True, warmup_laps_left=1), ST, True)[0].startswith(
        "Warm-up lap"
    )
    # Past the warm-up laps nothing is being learned yet, and it is not the driver's doing: the game
    # has not said where its sector lines are. Say what is actually happening, not "learning".
    text = status_line(snap(warming_up=True), ST, True)[0]
    assert text == "Waiting for the game's sector lines"


def test_the_distance_readout_names_the_phase_it_is_in():
    # It said "learning…" for every empty phase, including the ones where the app learns nothing.
    from brake_trainer.ui.status import phase_label

    assert phase_label(snap(warming_up=True, warmup_laps_left=1), ST) == "warm-up"
    assert phase_label(snap(warming_up=True), ST) == "waiting…"
    assert phase_label(snap(), ST) == "learning…"
    assert phase_label(snap(), Settings(learning_enabled=False)) == "paused"


def test_recent_result_is_shown_in_its_colour_then_gives_way():
    s = snap(last_result=result(), last_result_age=2.0)
    assert status_line(s, ST, True) == ("S2 18.01 s · best", theme.SECTOR_BEST)
    good = snap(last_result=result(SectorStatus.GOOD), last_result_age=1.0)
    assert status_line(good, ST, True)[1] == theme.SECTOR_GOOD
    old = snap(last_result=result(), last_result_age=30.0)
    assert status_line(old, ST, True)[0] == "2 braking points"


def test_a_result_says_how_far_off_the_sector_best_it_was():
    # Green/yellow is a rank (see the next test), so the time alone does not explain the colour;
    # the delta to the best is what tells the driver whether the run was close.
    slower = result(SectorStatus.SLOWER, duration=18.44, best=18.01, note="not kept")
    assert status_line(snap(last_result=slower, last_result_age=1.0), ST, True) == (
        "S2 18.44 s · slower (+0.43 s)",
        theme.SECTOR_SLOWER,
    )
    good = result(SectorStatus.GOOD, duration=18.12, best=18.01)
    assert status_line(snap(last_result=good, last_result_age=1.0), ST, True)[0] == (
        "S2 18.12 s · good (+0.11 s)"
    )
    # A new best is measured against the best it replaced, so the gain shows too.
    best = result(SectorStatus.BEST, duration=17.88, best=17.88, was=18.01)
    assert status_line(snap(last_result=best, last_result_age=1.0), ST, True)[0] == (
        "S2 17.88 s · best (-0.13 s)"
    )
    # The first run of a sector has nothing to compare with, so it shows no delta.
    first = result(SectorStatus.BEST, duration=18.01)
    assert status_line(snap(last_result=first, last_result_age=1.0), ST, True)[0] == (
        "S2 18.01 s · best"
    )
    assert slower.describe() == "S2 18.44s not kept (best 18.01s, +0.43s)"


def test_not_counted_result_explains_why_but_warm_up_noise_is_hidden():
    bad = result(duration=None, note="not counted · off track")
    assert status_line(snap(last_result=bad, last_result_age=1.0), ST, True)[0] == (
        "S2 not counted · off track"
    )
    warm = result(duration=None, note="not counted · warm-up lap")
    assert status_line(snap(last_result=warm, last_result_age=1.0), ST, True)[0] == (
        "2 braking points"
    )


def test_reference_and_idle_fallbacks():
    ref = snap(reference_car="BMW M4", reference_sectors=(1,))
    assert status_line(ref, ST, True)[0] == "Reference: BMW M4"
    assert status_line(snap(zones=()), ST, True)[0] == "No braking points yet"


def test_idle_summary_mentions_equal_sector_lines():
    text = status_line(snap(equal_lines=True), ST, True)[0]
    assert text == "2 braking points · equal sector lines"


def test_a_cut_reported_for_a_lap_that_is_gone_is_announced():
    # The sector bar shows the lap being driven, so a cut the log reports for an earlier lap has
    # nowhere else to appear; it outranks the current sector's own flag, which the bar shows anyway.
    s = snap(
        late_cut="S3 of the last lap won't count · cut",
        late_cut_age=3.0,
        pass_flag="lap invalidated",
    )
    assert status_line(s, ST, True) == ("S3 of the last lap won't count · cut", theme.RED)
    # ... and it stops after a while, giving the line back
    stale = snap(late_cut="S3 of the last lap won't count · cut", late_cut_age=60.0)
    assert status_line(stale, ST, True)[0] == "2 braking points"


def test_a_telemetry_failure_is_visible_even_when_not_live():
    # No sample is arriving, which is exactly when the reason has to be shown: the overlay would
    # otherwise just say it is waiting for the game.
    text = "Telemetry failed: capture could not start · see brake_trainer.log"
    assert status_line(snap(), ST, False, text) == (text, theme.RED)

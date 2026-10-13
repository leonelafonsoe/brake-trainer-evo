from __future__ import annotations

from brake_trainer.config import Settings
from brake_trainer.models import SectorResult, SectorStatus, Snapshot
from brake_trainer.ui import theme
from brake_trainer.ui.status import status_line

ST = Settings()


def snap(**kw) -> Snapshot:
    base = {"sector": 2, "zones": (0.1, 0.5)}
    return Snapshot(**{**base, **kw})


def result(status=SectorStatus.BEST, duration=18.01, note="kept"):
    return SectorResult(1, duration, True, duration, note, 1, status)


def test_nothing_to_say_when_not_live():
    assert status_line(snap(), ST, live=False) is None


def test_current_sector_that_will_not_count_has_top_priority():
    text, colour = status_line(snap(pass_flag="lap invalidated", warming_up=True), ST, True)
    assert text == "S3 won't count · lap invalidated" and colour == theme.RED


def test_paused_and_warm_up_states():
    assert status_line(snap(), Settings(learning_enabled=False), True)[0] == "Learning paused"
    assert status_line(snap(warming_up=True), ST, True)[0].startswith("Warm-up lap")


def test_recent_result_is_shown_in_its_colour_then_gives_way():
    s = snap(last_result=result(), last_result_age=2.0)
    assert status_line(s, ST, True) == ("S2 18.01 s · best", theme.SECTOR_BEST)
    good = snap(last_result=result(SectorStatus.GOOD), last_result_age=1.0)
    assert status_line(good, ST, True)[1] == theme.SECTOR_GOOD
    old = snap(last_result=result(), last_result_age=30.0)
    assert status_line(old, ST, True)[0] == "2 braking points"


def test_not_counted_result_explains_why_but_warm_up_noise_is_hidden():
    bad = result(duration=None, note="not counted (off track)")
    assert status_line(snap(last_result=bad, last_result_age=1.0), ST, True)[0] == (
        "S2 not counted (off track)"
    )
    warm = result(duration=None, note="not counted (warm-up lap)")
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

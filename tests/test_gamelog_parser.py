from __future__ import annotations

from datetime import datetime

from brake_trainer.gamelog import REPORTED_CUT, line_time, parse_line

from .gamelog_helpers import FIXTURES, NOTIFICATION, SPLIT

# The SDK's 0.2.2 regression data addition line, verbatim; see the fixture README.
SDK_ADDED = "[2026-08-18 23:13:02.935] [gameface] [warning] true {PENALTY_ADDED_KEY} #0 "


def test_the_games_cut_notification_is_reported():
    event = parse_line(NOTIFICATION)
    assert event is not None and event.cut and event.split == -1
    assert parse_line("[x] some other line") is None


def test_the_penalty_type_warning_is_not_a_second_cut():
    # The current build follows every SessionPenalty notification with
    # `false {PENALTY_CLEARED_KEY}`. That line says which HUD text the notification carries, not
    # that no cut happened: the notification is the cut verdict, and the warning adds nothing.
    assert parse_line(NOTIFICATION)
    cleared = "[2026-10-23 01:34:55.051] [gameface] [warning] false {PENALTY_CLEARED_KEY} #296 "
    assert parse_line(cleared) is None


def test_the_sdk_penalty_addition_is_a_cut():
    event = parse_line(SDK_ADDED)
    assert event is not None and event.cut == REPORTED_CUT and event.split == -1


def test_a_plain_notification_without_adding_is_not_a_cut():
    # `UINotification ... SessionPenalty` only names the HUD text. The addition line is the cut
    # verdict, so matching the type name on its own would report every cut twice.
    plain = (
        "[2026-10-23 01:40:35.562] [gameface] [info] "
        "UINotification UINotificationType_SessionPenalty"
    )
    assert parse_line(plain) is None


def test_two_additions_in_one_lap_are_both_reported():
    # There is no time window: two additions at different times are two cuts. The engine folds them
    # by (lap, sector), so suppressing the second here would hide a real cut in another sector.
    later = (
        "[2026-10-16 20:41:52.703] [gameface] [info] "
        "Adding notification UINotificationType_SessionPenalty"
    )
    events = [parse_line(line) for line in (NOTIFICATION, later)]
    assert [event.cut if event is not None else "" for event in events] == [
        REPORTED_CUT,
        REPORTED_CUT,
    ]


def _parse_fixture(name: str) -> list[tuple[str, int]]:
    """Parse a real game-log excerpt, returning its ``(cut, split)`` events."""
    events: list[tuple[str, int]] = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        event = parse_line(line)
        if event is not None:
            events.append((event.cut, event.split))
    return events


def test_a_real_monza_notification_block_reports_one_cut_after_its_split():
    assert _parse_fixture("notification_block.txt") == [("", 0), (REPORTED_CUT, -1)]


def test_the_sdk_shaped_fixture_reports_only_its_addition():
    assert _parse_fixture("penalty_sdk_build.txt") == [(REPORTED_CUT, -1)]


def test_real_monza_sector_lines_report_all_three_indices():
    assert _parse_fixture("splits.txt") == [("", 0), ("", 1), ("", 2)]


def test_real_lines_around_a_notification_do_not_add_a_second_event():
    assert _parse_fixture("noise.txt") == []


def test_the_games_sector_splits_are_reported():
    event = parse_line(SPLIT)
    assert event is not None and event.split == 1 and event.cut == ""
    # The end of the third sector is the start/finish line, which is not a sector line to learn.
    last = parse_line("[t] Received split: isStart true, isEnd true, index 2 ")
    assert last is not None and last.split == 2


def test_a_line_time_is_read_from_the_line_and_missing_ones_are_not_guessed():
    assert line_time(NOTIFICATION) == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()
    assert line_time("[no timestamp here]") is None
    assert line_time("[2026-13-99 99:99:99.999] broken") is None

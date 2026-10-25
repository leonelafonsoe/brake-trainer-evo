from __future__ import annotations

from datetime import datetime

from brake_trainer.gamelog import REPORTED_CUT, LogState, line_time, parse_line

from .gamelog_helpers import (
    AI,
    AI_CONNECT,
    CONNECT,
    FIXTURES,
    NOTIFICATION,
    PLAYER,
    SPLIT,
    limits,
    player_state,
)


def test_the_games_cut_notification_is_reported():
    event = parse_line(NOTIFICATION, LogState())
    assert event is not None and event.cut and event.split == -1
    assert parse_line("[x] some other line", LogState()) is None


def test_the_penalty_type_warning_is_not_a_second_cut():
    # The current build follows every SessionPenalty notification with
    # `false {PENALTY_CLEARED_KEY}`. That line says which HUD text the notification carries, not
    # that no cut happened: the notification is the cut verdict, and the warning adds nothing.
    state = LogState()
    assert parse_line(NOTIFICATION, state)
    cleared = "[2026-10-23 01:34:55.051] [gameface] [warning] false {PENALTY_CLEARED_KEY} #296 "
    assert parse_line(cleared, state) is None


def _parse_fixture(name: str) -> tuple[LogState, list[tuple[str, int]]]:
    """Parse a real game-log excerpt, returning its state and ``(cut, split)`` events."""
    state = LogState()
    events: list[tuple[str, int]] = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        event = parse_line(line, state)
        if event is not None:
            events.append((event.cut, event.split))
    return state, events


def test_a_real_monza_notification_block_reports_one_cut_after_its_split():
    _, events = _parse_fixture("notification_block.txt")
    assert events == [("", 0), (REPORTED_CUT, -1)]


def test_real_monza_sector_lines_report_all_three_indices():
    _, events = _parse_fixture("splits.txt")
    assert events == [("", 0), ("", 1), ("", 2)]


def test_a_real_connect_line_learns_the_players_car():
    state, events = _parse_fixture("connect.txt")
    assert events == []
    assert state.player_uuids == {"0123456789abcdeffedcba9876543210"}


def test_real_lines_around_a_notification_do_not_add_a_second_event():
    _, events = _parse_fixture("noise.txt")
    assert events == []


def test_the_games_sector_splits_are_reported():
    event = parse_line(SPLIT, LogState())
    assert event is not None and event.split == 1 and event.cut == ""
    # The end of the third sector is the start/finish line, which is not a sector line to learn.
    last = parse_line("[t] Received split: isStart true, isEnd true, index 2 ", LogState())
    assert last is not None and last.split == 2


def test_a_violation_is_all_four_tyres_out_two_metres_or_more_for_the_player():
    state = player_state()
    assert parse_line(limits(PLAYER, 4, 2.62), state)
    assert parse_line(limits(PLAYER, 4, 2.0), state)
    assert not parse_line(limits(PLAYER, 4, 1.4), state)  # brief excursion: tolerated
    assert not parse_line(limits(PLAYER, 3, 3.0), state)  # not all four tyres
    assert not parse_line(limits(PLAYER, 4, 12.52), state)  # teleported to the pits
    assert not parse_line(limits(AI, 4, 3.0), state)  # someone else's car
    # A limits line this build cannot read is ignored, not guessed at.
    assert not parse_line("[t] Limits: car broken tyres out changed", state)


def test_the_player_is_the_car_with_a_steam_id_and_unknown_cars_are_ignored():
    state = LogState()
    assert not parse_line(limits(PLAYER, 4, 3.0), state)  # nothing known yet
    parse_line(CONNECT, state)
    assert parse_line(limits(PLAYER, 4, 3.0), state)
    # the first car with a non-Steam id is the player's when no Steam id is ever seen
    offline = LogState()
    parse_line(AI_CONNECT, offline)
    assert parse_line(limits(AI, 4, 3.0), offline)


def test_a_line_time_is_read_from_the_line_and_missing_ones_are_not_guessed():
    assert line_time(NOTIFICATION) == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()
    assert line_time("[no timestamp here]") is None
    assert line_time("[2026-13-99 99:99:99.999] broken") is None

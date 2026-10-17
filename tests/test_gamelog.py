from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.gamelog import GameLogTail, LogState, line_time, parse_line
from brake_trainer.models import SectorStatus

from .conftest import Driver

PLAYER = "0a1b2c3d-1111-2222-3333-444455556666"
AI = "ffffffff-aaaa-bbbb-cccc-000011112222"
CONNECT = (
    "[2026-10-14 21:00:00.100] [network] [info] 76561198000000001 connected (true) on car "
    f"ferrari_296_gtb, with new carId {PLAYER}"
)
AI_CONNECT = (
    f"[2026-10-14 21:00:00.200] [network] [info] 0 connected (false) on car bmw_m4, "
    f"with new carId {AI}"
)
# One HUD notification per cut, written once the give-back window has passed (build 0.5+).
NOTIFICATION = (
    "[2026-10-16 20:41:38.703] [gameface] [info] "
    "Adding notification UINotificationType_SessionPenalty "
)


def limits(car: str, tyres: int, inside: float) -> str:
    return (
        f"[2026-10-14 21:05:00.000] [physics] [info] Limits: car {car} "
        f"tyres out changed: 3 -> {tyres} with {inside}m inside"
    )


def player_state() -> LogState:
    state = LogState()
    parse_line(CONNECT, state)
    parse_line(AI_CONNECT, state)
    return state


def test_the_games_cut_notification_is_reported():
    assert parse_line(NOTIFICATION, LogState())
    assert not parse_line("[x] some other line", LogState())


def test_a_violation_is_all_four_tyres_out_two_metres_or_more_for_the_player():
    state = player_state()
    assert parse_line(limits(PLAYER, 4, 2.62), state)
    assert parse_line(limits(PLAYER, 4, 2.0), state)
    assert not parse_line(limits(PLAYER, 4, 1.4), state)  # brief excursion: tolerated
    assert not parse_line(limits(PLAYER, 3, 3.0), state)  # not all four tyres
    assert not parse_line(limits(PLAYER, 4, 12.52), state)  # teleported to the pits
    assert not parse_line(limits(AI, 4, 3.0), state)  # someone else's car


def test_the_player_is_the_car_with_a_steam_id_and_unknown_cars_are_ignored():
    state = LogState()
    assert not parse_line(limits(PLAYER, 4, 3.0), state)  # nothing known yet
    parse_line(CONNECT, state)
    assert parse_line(limits(PLAYER, 4, 3.0), state)
    # the first car with a non-Steam id is the player's when no Steam id is ever seen
    offline = LogState()
    parse_line(AI_CONNECT, offline)
    assert parse_line(limits(AI, 4, 3.0), offline)


async def _wait(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_tail_reports_only_new_cuts_and_follows_newer_logs(tmp_path: Path):
    old = tmp_path / "old.txt"
    old.write_text("\n".join([CONNECT, NOTIFICATION]) + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(
        tmp_path, lambda reason, at: hits.append((reason, at)), poll_s=0.01, rescan_s=0.02
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    await asyncio.sleep(0.3)
    assert hits == []  # history is not replayed

    with old.open("a", encoding="utf-8") as fh:
        fh.write(limits(AI, 4, 3.0) + "\n")  # not the player
        fh.write(NOTIFICATION[:30])  # a line written in two pieces
        fh.flush()
        await asyncio.sleep(0.1)
        assert hits == []
        fh.write(NOTIFICATION[30:] + "\n")
    assert await _wait(lambda: len(hits) == 1)
    # The time is the line's own, not when it was read: the game buffers this log.
    assert hits[0][1] == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()

    new = tmp_path / "new.txt"  # the game was restarted
    new.write_text(CONNECT + "\n" + NOTIFICATION + "\n", encoding="utf-8")
    os.utime(new, (time.time() + 5, time.time() + 5))
    await asyncio.sleep(0.3)
    assert len(hits) == 1  # its first content is history too
    with new.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    assert await _wait(lambda: len(hits) == 2)
    stop.set()
    await asyncio.wait_for(task, 2)


def test_a_line_time_is_read_from_the_line_and_falls_back_when_missing():
    fallback = 1234.5
    assert (
        line_time(NOTIFICATION, fallback) == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()
    )
    assert line_time("[no timestamp here]", fallback) == fallback
    assert line_time("[2026-13-99 99:99:99.999] broken", fallback) == fallback


async def test_tail_without_a_log_folder_just_says_so(tmp_path: Path):
    messages: list[str] = []
    tail = GameLogTail(
        tmp_path / "missing",
        lambda reason, at: None,
        messages.append,
        poll_s=0.01,
        rescan_s=0.01,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    await asyncio.sleep(0.15)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert any("No game log found" in m for m in messages)


# ---- the engine side


CORNERS = [0.20, 0.50, 0.80]


def _engine(store, **settings):
    """A warmed-up engine on a 5-sector, 5000 m track: a 500 m lookback is 0.1 of a lap."""
    results: list = []
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(n_sectors=5, warmup_laps=0, **settings),
        store,
        on_sector=results.append,
        on_message=messages.append,
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    messages.clear()
    return engine, driver, results, messages


def stored_times(store, sector: int) -> list[float]:
    return [r.t for r in store.load("Monza", "Car A", 5).sectors[sector]]


def test_a_cut_reported_in_a_later_sector_is_taken_back_to_where_it_happened(store):
    # The cut is in S2 (0.4..0.6). The game only reports it after the give-back window, by which
    # time the car is in S3; S2's faster run must be taken back, not S3 dropped.
    engine, driver, _, messages = _engine(store)
    before = stored_times(store, 2)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.63)  # S2 closed and was saved
    assert stored_times(store, 2)[0] < before[0]
    engine.report_infraction("the game reported a cut", driver.t)
    assert stored_times(store, 2) == before
    assert any("taken back" in m for m in messages)
    assert engine.snapshot().pass_flag != "off track"  # S3, the sector it was reported in, is clean


def test_a_cut_reported_while_still_in_its_sector_drops_that_sector(store):
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # in S2, 500 m past the cut
    engine.report_infraction("the game reported a cut", driver.t)
    snap = engine.snapshot()
    assert snap.sector == 2 and snap.pass_flag == "off track"


def test_a_cut_read_late_is_still_dropped_in_the_sector_it_happened_in(store):
    # The game buffers its log, so this cut is read long after it was written - here when the car is
    # already past the 0.6 line. The line carries its own time, so it still lands in the sector it
    # happened in (0.4..0.6), half a give-back window behind where the car was when it was written.
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # 0.4..0.6, past a cut there
    written_at = driver.t
    driver.lap(
        CORNERS, speed_fn=lambda p: 215, start=0.56, stop=0.78
    )  # by now the car is in 0.6..0.8
    assert engine.snapshot().sector == 3
    engine.report_infraction("the game reported a cut", written_at)
    snap = engine.snapshot()
    assert snap.sector_status[2] is SectorStatus.PENDING  # 0.4..0.6, where the cut happened
    assert snap.pass_flag == ""  # 0.6..0.8, where the line was read, was driven cleanly
    assert engine.snapshot().sector == 3


def test_two_cuts_read_in_one_batch_each_drop_their_own_sector(store):
    # A buffered log can hold a minute of lines, so a batch can carry cuts from far apart. Each is
    # attributed from its own time: both sectors go, and the clean one between them stays.
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.35)  # a cut judged in 0.2..0.4
    first = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.36, stop=0.72)  # one judged in 0.6..0.8
    second = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.73, stop=0.95)  # read only now, together
    engine.report_infraction("the game reported a cut", first)
    engine.report_infraction("the game reported a cut", second)
    status = engine.snapshot().sector_status
    assert status[1] is SectorStatus.PENDING  # 0.2..0.4
    assert status[3] is SectorStatus.PENDING  # 0.6..0.8
    assert status[2] is not SectorStatus.PENDING  # 0.4..0.6, between them, was clean
    assert engine.snapshot().pass_flag == ""  # the sector they were read in is clean


def test_the_give_back_distance_can_be_switched_off(store):
    # 0 = trust the position the report arrives at, so the sector in progress is the one dropped.
    engine, driver, _, _ = _engine(store, cut_give_back_m=0)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.63)
    engine.report_infraction("the game reported a cut", driver.t)
    snap = engine.snapshot()
    assert snap.sector == 3 and snap.pass_flag == "off track"


def test_two_late_reported_cuts_drop_only_their_own_sectors(store):
    # The real case: a cut in S3 and another in S5, each reported a give-back window later. Only
    # those two sectors go; every clean sector of the lap stays.
    engine, driver, results, _ = _engine(store)
    before = [stored_times(store, i) for i in range(5)]
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.63)  # into S4; S3's cut is now reported
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.64, stop=0.93)  # into S5's cut
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.94, stop=1.003)
    by_sector = {r.sector: r for r in results}
    assert stored_times(store, 2) == before[2]  # S3's faster run was taken back
    assert by_sector[4].duration is None and "off track" in by_sector[4].note  # S5 dropped
    for clean in (0, 1, 3):
        assert by_sector[clean].accepted


def test_a_cut_in_a_sector_that_was_not_saved_still_shows_as_not_counted(store):
    # The cut sector's time may already be slower than the best, so there is no run to take back;
    # the sector must still stop counting.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 195, stop=0.63)  # slower than the warm-up runs
    engine.report_infraction("the game reported a cut", driver.t)
    assert engine.snapshot().sector_status[2] is SectorStatus.PENDING
    assert any("will not count" in m for m in messages)


def test_cuts_are_ignored_when_invalid_sectors_are_not_skipped(store):
    engine, driver, results, _ = _engine(store, skip_invalid_sectors=False)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.56, stop=1.003)
    assert {r.sector: r for r in results}[2].accepted


def test_a_cut_the_lap_flag_already_stood_for_is_not_counted_twice(store):
    # The log notification and the lap flag describe the same cut; a second signal so soon after
    # the first must not drop another sector.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.63)
    engine.report_infraction("the game reported a cut", driver.t)
    engine.report_infraction("the game reported a cut", driver.t)  # the same cut, a second signal
    assert sum("reported a cut" in m for m in messages) == 1

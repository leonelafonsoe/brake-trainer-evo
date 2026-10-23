from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from brake_trainer.config import Settings
from brake_trainer.engine import N_SECTORS, BrakeEngine
from brake_trainer.gamelog import GameLogTail, LogState, line_time, parse_line
from brake_trainer.models import SectorStatus

from .conftest import DT, LENGTH, Driver

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
# The end of one of the game's three sectors, written the moment the car crosses its line.
SPLIT = (
    "[2026-10-16 20:41:00.000] [gameplay] [info] "
    "Received split: isStart false, isEnd false, index 1 "
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
    event = parse_line(NOTIFICATION, LogState())
    assert event is not None and event.cut and event.split == -1
    assert parse_line("[x] some other line", LogState()) is None


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


async def test_tail_reports_the_sector_splits_it_reads(tmp_path: Path):
    log = tmp_path / "log.txt"
    log.write_text(CONNECT + "\n", encoding="utf-8")
    splits: list[tuple[int, float]] = []
    tail = GameLogTail(
        tmp_path,
        lambda reason, at: None,
        on_split=lambda index, at: splits.append((index, at)),
        poll_s=0.01,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    await asyncio.sleep(0.15)
    assert splits == []  # history is not replayed

    with log.open("a", encoding="utf-8") as fh:
        fh.write(SPLIT + "\n")
    assert await _wait(lambda: len(splits) == 1)
    assert splits[0][0] == 1
    assert splits[0][1] == datetime(2026, 10, 16, 20, 41, 0, 0).timestamp()
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
    """A warmed-up engine on a 5000 m track: a 500 m lookback is 0.1 of a lap.

    The lookback is pinned here so these tests exercise the attribution, not the shipped default of
    0, which would keep several of the cuts inside the sector the report lands in. The lines are the
    game's three: equal splits (1/3 and 2/3), since no split is reported to this engine.
    """
    settings.setdefault("cut_give_back_m", 500.0)
    results: list = []
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0, **settings),
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
    return [r.t for r in store.load("Monza", "Car A", N_SECTORS).sectors[sector]]


def test_a_cut_reported_in_a_later_sector_is_taken_back_to_where_it_happened(store):
    # The cut is in S1 (0..1/3). The game only reports it after the give-back window, by which time
    # the car is in S2; S1's faster run must be taken back, not S2 dropped.
    engine, driver, _, messages = _engine(store)
    before = stored_times(store, 0)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.40)  # S1 closed and was saved
    assert stored_times(store, 0)[0] < before[0]
    engine.report_infraction("the game reported a cut", driver.t)
    assert stored_times(store, 0) == before
    assert any("taken back" in m for m in messages)
    assert engine.snapshot().pass_flag != "off track"  # S2, the sector it was reported in, is clean


def test_a_cut_reported_while_still_in_its_sector_drops_that_sector(store):
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # in S2 (1/3..2/3), 500 m past the cut
    engine.report_infraction("the game reported a cut", driver.t)
    snap = engine.snapshot()
    assert snap.sector == 1 and snap.pass_flag == "off track"


def test_a_cut_read_late_is_still_dropped_in_the_sector_it_happened_in(store):
    # The game buffers its log, so this cut is read long after it was written - here when the car is
    # already past the 2/3 line. The line carries its own time, so it still lands in the sector it
    # happened in (1/3..2/3), half a give-back window behind where the car was when it was written.
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # 1/3..2/3, past a cut there
    written_at = driver.t
    driver.lap(
        CORNERS, speed_fn=lambda p: 215, start=0.56, stop=0.78
    )  # by now the car is in 2/3..1
    assert engine.snapshot().sector == 2
    engine.report_infraction("the game reported a cut", written_at)
    snap = engine.snapshot()
    assert snap.sector_status[1] is SectorStatus.PENDING  # 1/3..2/3, where the cut happened
    assert snap.pass_flag == ""  # 2/3..1, where the line was read, was driven cleanly
    assert engine.snapshot().sector == 2


def test_two_cuts_read_in_one_batch_each_drop_their_own_sector(store):
    # A buffered log can hold a minute of lines, so a batch can carry cuts from far apart. Each is
    # attributed from its own time: both sectors go, and the clean one between them stays.
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.30)  # a cut judged in S1
    first = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.31, stop=0.90)  # one judged in S3
    second = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.91, stop=0.95)  # read only now, together
    engine.report_infraction("the game reported a cut", first)
    engine.report_infraction("the game reported a cut", second)
    status = engine.snapshot().sector_status
    assert status[0] is SectorStatus.PENDING  # S1
    assert status[2] is SectorStatus.PENDING  # S3, the sector being driven
    assert status[1] is not SectorStatus.PENDING  # S2, between them, was clean
    assert engine.snapshot().pass_flag == "off track"  # S3 is where the second one is attributed


def test_a_cut_read_a_lap_late_takes_back_that_laps_run_not_a_later_ones(store):
    # The game buffers its log, so this cut is only read after the lap it belongs to has ended and
    # a later lap has stored its own, faster run in the same sector. Only the earlier lap's run
    # goes, and the message says which lap it was.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # judged with the car at 0.55: the cut
    written_at = driver.t  # is 500 m back at 0.45, in S2 (1/3..2/3)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.56, stop=1.003)  # lap A: S2 saved
    lap_a = stored_times(store, 1)
    driver.lap(CORNERS, speed_fn=lambda p: 230, start=0.001, stop=0.70)  # lap B: faster S2
    lap_b = stored_times(store, 1)
    assert lap_b[0] < lap_a[0]

    engine.report_infraction("the game reported a cut", written_at)

    after = stored_times(store, 1)
    assert after[0] == lap_b[0]  # the clean run of the lap driven since is kept
    assert lap_a[0] not in after  # the cut lap's run was taken back
    assert any("in the previous lap" in m and "taken back" in m for m in messages)


def test_a_cut_read_a_lap_late_does_not_mark_the_sector_of_the_lap_being_driven(store):
    # By the time it is read the sector bar shows the lap being driven (its first sector has closed,
    # so the last lap's colours are gone). The cut must not grey a sector of that lap: it belongs to
    # the one before, and the status line names it instead.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # the cut, as above
    written_at = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.56, stop=1.003)  # lap A ends
    driver.lap(CORNERS, speed_fn=lambda p: 205, start=0.001, stop=0.70)  # lap B: S2 clean
    on_screen = engine.snapshot().sector_status[1]
    assert on_screen is not SectorStatus.PENDING

    engine.report_infraction("the game reported a cut", written_at)

    after = engine.snapshot()
    assert after.sector_status[1] is on_screen  # left alone
    assert after.late_cut == "S2 of the last lap won't count · cut"  # said on the status line
    assert after.late_cut_age == 0.0
    assert any("in the previous lap" in m for m in messages)


def test_a_lap_flag_dropping_just_after_the_line_takes_back_the_previous_laps_run(store):
    # A cut on the last corner is judged a give-back window later, so the flag can drop just after
    # the line. The cut belongs to the lap that has just ended: its run is taken back and its sector
    # - still on the bar, since this lap's first sector has not closed - is greyed, not this lap's.
    engine, driver, _, _ = _engine(store)
    p = driver.lap(CORNERS, speed_fn=lambda p: 215)  # lap A ends: S3 saved as the new best
    lap_a = stored_times(store, 2)
    assert lap_a and engine.snapshot().sector_status[2] is not SectorStatus.PENDING

    driver.lap(CORNERS, speed_fn=lambda p: 215, start=p, stop=p + 0.03, invalid_from=1.01)

    assert engine.snapshot().sector_status[2] is SectorStatus.PENDING  # the last lap's S3, greyed
    assert lap_a[0] not in stored_times(store, 2)  # and its run taken back


def test_a_cut_from_before_the_kept_history_is_skipped_rather_than_guessed(store):
    # Guessing from the current position would drop whatever sector the car is in now, which is
    # worse than saying nothing: a report older than the kept history is dropped.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.85)
    engine.report_infraction("the game reported a cut", driver.t - 1000.0)
    assert engine.snapshot().pass_flag == ""
    assert not any("reported a cut" in m for m in messages)


def test_the_shipped_default_takes_the_reported_position_as_it_is(store):
    # The game reports a cut at the corner it happened in, so no lookback is applied by default:
    # a report made inside a sector drops that sector.
    assert Settings().cut_give_back_m == 0.0
    engine, driver, _, messages = _engine(store, cut_give_back_m=Settings().cut_give_back_m)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    engine.report_infraction("the game reported a cut", driver.t)
    assert engine.snapshot().pass_flag == "off track"
    assert any("S2 won't count" in m for m in messages)


def test_a_give_back_window_still_steps_a_report_back_when_one_is_set(store):
    # The window is still honoured for data that asks for it: a cut reported just past a line then
    # belongs to the sector it was read back into.
    engine, driver, _, messages = _engine(store, cut_give_back_m=500.0)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.70)  # 500 m is 0.1 of this 5000 m track
    engine.report_infraction("the game reported a cut", driver.t)
    assert engine.snapshot().sector == 2  # the driver is in S3 ...
    assert any("S2 had its stored run taken back" in m for m in messages)  # ... read in S2


def test_a_zero_give_back_window_trusts_the_reported_position(store):
    # 0 = trust the position the report arrives at, so the sector in progress is the one dropped.
    engine, driver, _, _ = _engine(store, cut_give_back_m=0)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    engine.report_infraction("the game reported a cut", driver.t)
    snap = engine.snapshot()
    assert snap.sector == 1 and snap.pass_flag == "off track"


def test_two_late_reported_cuts_drop_only_their_own_sectors(store):
    # The real case: a cut in S2 and another in S3, each reported a give-back window later. Only
    # those two sectors go; the clean first sector of the lap stays.
    engine, driver, results, _ = _engine(store)
    before = [stored_times(store, i) for i in range(N_SECTORS)]
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.70)  # into S3; S2's cut is now reported
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.71, stop=0.95)  # into S3's own cut
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.96, stop=1.003)
    by_sector = {r.sector: r for r in results}
    assert stored_times(store, 1) == before[1]  # S2's faster run was taken back
    assert by_sector[2].duration is None and "off track" in by_sector[2].note  # S3 dropped
    assert by_sector[0].accepted  # the clean sector is kept


def test_two_cuts_reported_seconds_apart_in_different_sectors_both_count(store):
    # Two reports can arrive in one read, seconds apart: one cut in S1 and another in S2. The second
    # must not be folded into the first, even though the app saw them close together in time.
    engine, driver, _, messages = _engine(store)
    driver.feed(0.30, 150.0, 0.0)
    first = driver.t
    driver.feed(0.60, 150.0, 0.0)
    second = driver.t

    engine.report_infraction("the game reported a cut", first)
    engine.report_infraction("the game reported a cut", second)

    assert sum("the game reported a cut" in m for m in messages) == 2
    status = engine.snapshot().sector_status
    assert status[0] is SectorStatus.PENDING  # S1, read back 500 m from the first report
    assert status[1] is SectorStatus.PENDING  # S2, read back from the second


def test_a_cut_reported_in_the_frame_that_wraps_the_line_stays_in_the_laps_last_sector(store):
    # A live cut just before the line drops S3 of the lap that is ending. The game's log line for
    # that same cut is read a moment later, with ``at`` inside the telemetry frame that wraps the
    # start/finish line. Both samples of that frame still carry the old lap number, so interpolating
    # across the wrap would return a position just after 0.0 labelled with the old lap: S1 of that
    # lap, a second sector. Backing off to the earlier sample keeps the line in S3, which the live
    # cut already dropped, so one cut still drops one sector.
    engine, driver, _, messages = _engine(store, cut_give_back_m=0)
    step = 200.0 / 3.6 * DT / LENGTH
    p = 0.0001
    while True:
        t0, p0 = driver.t, p % 1.0
        p += step
        # The lap flag falls just before the line; the sample after the wrap is clean.
        driver.feed(p % 1.0, 200.0, 0.0, valid=p < 0.9995 or p % 1.0 < 0.5)
        if p % 1.0 < p0:  # the start/finish line lies between these two samples
            t1, p1 = driver.t, p % 1.0
            break

    lap = engine._lap_no  # the lap number the wrap has just moved on to
    assert (lap - 1, 2) in engine._invalid_sectors  # the live cut's S3 of the lap that ended
    at = (engine._line_crossing(t0, p0, t1, p1, 0.0) + t1) / 2
    engine.report_infraction("off track", at)

    assert (lap - 1, 2) in engine._invalid_sectors  # still that lap's S3
    assert (lap - 1, 0) not in engine._invalid_sectors  # not a second sector, its S1
    assert not any("S1" in m and "previous lap" in m for m in messages)


def test_a_cut_in_a_sector_that_was_not_saved_still_shows_as_not_counted(store):
    # The cut sector's time may already be slower than the best, so there is no run to take back;
    # the sector must still stop counting.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 195, stop=0.70)  # slower than the warm-up runs
    engine.report_infraction("the game reported a cut", driver.t)
    assert engine.snapshot().sector_status[1] is SectorStatus.PENDING
    # The message names the sector rather than saying "this sector", so the driver can tell which
    # cell on the bar just went grey (the app counts sectors from 1, so 1/3..2/3 is S2).
    assert any("S2 won't count" in m for m in messages)


def test_cuts_are_ignored_when_invalid_sectors_are_not_skipped(store):
    engine, driver, results, _ = _engine(store, skip_invalid_sectors=False)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.56, stop=1.003)
    assert {r.sector: r for r in results}[1].accepted


def test_a_cut_in_a_warm_up_sector_is_not_announced(store):
    # The sector was already going to be skipped, so announcing the cut would only repeat what the
    # result is about to say. It still goes into the pass so the result names a reason.
    messages: list[str] = []
    results: list = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1),
        store,
        on_message=messages.append,
        on_sector=results.append,
    )
    driver = Driver(engine)
    p = driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    engine.report_infraction("the game reported a cut", driver.t)
    assert not any("reported a cut" in m for m in messages)

    driver.lap(CORNERS, start=p, stop=0.70)
    s2 = next(r for r in results if r.sector == 1)
    assert s2.note == "not counted · warm-up lap"


def test_a_late_cut_in_a_warm_up_lap_is_not_announced(store):
    # The same, when the log is read after that lap is over: the reminder would arrive with no
    # sector on the bar left to grey and nothing to take back.
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1), store, on_message=messages.append
    )
    driver = Driver(engine)
    p = driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)
    cut_at = driver.t
    driver.lap(CORNERS, start=p, stop=1.003)  # finish the warm-up lap
    messages.clear()

    engine.report_infraction("the game reported a cut", cut_at)
    assert not any("reported a cut" in m for m in messages)
    assert engine.snapshot().late_cut == ""


def test_a_notice_the_lap_flag_already_stood_for_is_not_counted_twice(store, caplog):
    # The game drops the lap flag the moment it judges a cut and writes the matching notice a
    # moment later. The notice must not drop a second sector - and it must still be recognised when
    # the same batch carries later cuts, which is where this went wrong on track: the earlier lines
    # of the batch moved the last-cut time on, and the notice was then counted a second time.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, invalid_from=0.6, stop=0.605)
    cut_at = driver.t
    engine.report_infraction("the game reported a cut", cut_at - 30.0)  # an earlier cut, same batch
    with caplog.at_level(logging.DEBUG):
        engine.report_infraction("the game reported a cut", cut_at)  # the notice for the flag's cut
    assert sum("reported a cut" in m for m in messages) == 1  # the earlier cut, and only that one
    assert any("already invalidated" in r.getMessage() for r in caplog.records)


def test_a_cut_read_twice_is_not_counted_twice(store, caplog):
    # The same notice must not drop two sectors either: a restart re-reads the whole log, so a line
    # recently read can be read again.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.63)
    engine.report_infraction("the game reported a cut", driver.t)
    with caplog.at_level(logging.DEBUG):
        engine.report_infraction("the game reported a cut", driver.t)  # the same line again
    assert sum("reported a cut" in m for m in messages) == 1
    assert any("already invalidated" in r.getMessage() for r in caplog.records)

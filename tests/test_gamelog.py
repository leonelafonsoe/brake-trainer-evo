from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from brake_trainer import gamelog as gamelog_module
from brake_trainer.config import Settings
from brake_trainer.engine import _HISTORY_S, N_SECTORS, BrakeEngine, _LapRun
from brake_trainer.gamelog import (
    DEFAULT_LOG_DIR,
    REPORTED_CUT,
    GameLogSupervisor,
    GameLogTail,
    LogState,
    line_time,
    parse_line,
)
from brake_trainer.models import SectorRun, SectorStatus, TrackData
from brake_trainer.timeline import crossing_between

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
# One HUD notification per cut, written when the game judges it (build 0.5+).
NOTIFICATION = (
    "[2026-10-16 20:41:38.703] [gameface] [info] "
    "Adding notification UINotificationType_SessionPenalty "
)
# The end of one of the game's three sectors, written the moment the car crosses its line.
SPLIT = (
    "[2026-10-16 20:41:00.000] [gameplay] [info] "
    "Received split: isStart false, isEnd false, index 1 "
)
# Real build 0.9.1 excerpts; see tests/fixtures/game_log/README.md.
FIXTURES = Path(__file__).with_name("fixtures") / "game_log"


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


def test_a_line_time_is_read_from_the_line_and_missing_ones_are_not_guessed():
    assert line_time(NOTIFICATION) == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()
    assert line_time("[no timestamp here]") is None
    assert line_time("[2026-13-99 99:99:99.999] broken") is None


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


async def test_a_larger_replacement_file_is_read_from_the_top_not_the_old_offset(
    tmp_path: Path,
):
    # The game starts a new log on every run; it can be larger than the one before. The old code
    # only reset when the file was *smaller*, so it resumed at the previous offset and reported the
    # middle of the new log's history as if it had just happened.
    log = tmp_path / "log.txt"
    original = CONNECT + "\n"
    log.write_text(original, encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(
        tmp_path, lambda reason, at: hits.append((reason, at)), poll_s=0.01, rescan_s=0.02
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    assert await _wait(lambda: tail._live)

    replacement = tmp_path / "next.txt"
    replacement.write_text(original + NOTIFICATION + "\n" + "x" * 200 + "\n", encoding="utf-8")
    os.replace(replacement, log)  # a new inode, larger than the old file
    await asyncio.sleep(0.15)
    assert hits == []  # the new file's existing content is history too

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    assert await _wait(lambda: len(hits) == 1)
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_only_the_start_of_a_large_log_is_read(tmp_path: Path, monkeypatch):
    # A stale log can be megabytes long. Only its top can name the player's car, and nothing in it
    # can be reported, so the rest is skipped instead of read and parsed line by line.
    monkeypatch.setattr(gamelog_module, "_MAX_FIRST_READ_BYTES", 300)
    log = tmp_path / "log.txt"
    log.write_text(CONNECT + "\n" + "x" * 500 + "\n" + NOTIFICATION + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(
        tmp_path, lambda reason, at: hits.append((reason, at)), poll_s=0.01, rescan_s=0.02
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    assert await _wait(lambda: tail._live)
    assert tail._offset == log.stat().st_size  # the rest of the history was skipped
    assert hits == []

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    assert await _wait(lambda: len(hits) == 1)
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_an_undated_event_is_skipped_and_warned_about_once(tmp_path: Path):
    # The line's own time is what places it. Without one, using the read time would file a buffered
    # event minutes late, so it is dropped - and the driver is told why, once.
    log = tmp_path / "log.txt"
    log.write_text(CONNECT + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    messages: list[str] = []
    tail = GameLogTail(
        tmp_path, lambda reason, at: hits.append((reason, at)), messages.append, poll_s=0.01
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    assert await _wait(lambda: tail._live)

    with log.open("a", encoding="utf-8") as fh:
        fh.write("[gameface] [info] Adding notification UINotificationType_SessionPenalty\n")
    await asyncio.sleep(0.1)
    assert hits == []
    assert messages.count("Ignoring game-log lines without a timestamp") == 1

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    assert await _wait(lambda: len(hits) == 1)
    stop.set()
    await asyncio.wait_for(task, 2)


class FakeTail:
    """Stands in for the real tail: records its folder and when it was stopped."""

    created: list[FakeTail] = []

    def __init__(self, directory, on_cut, on_message, on_split=lambda index, at: None) -> None:
        self.directory = directory
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        FakeTail.created.append(self)

    async def run(self, stop: asyncio.Event) -> None:
        self.started.set()
        try:
            await stop.wait()
        finally:
            self.finished.set()


async def test_the_supervisor_follows_runtime_settings(tmp_path: Path, monkeypatch):
    FakeTail.created.clear()
    monkeypatch.setattr(gamelog_module, "GameLogTail", FakeTail)
    current = {"settings": Settings(use_game_log=False)}
    stop = asyncio.Event()
    supervisor = GameLogSupervisor(
        lambda: current["settings"], lambda reason, at: None, poll_s=0.01
    )
    task = asyncio.create_task(supervisor.run(stop))
    await asyncio.sleep(0.05)
    assert FakeTail.created == []  # disabled: no tail at all

    current["settings"] = replace(current["settings"], use_game_log=True)
    assert await _wait(lambda: len(FakeTail.created) == 1)
    first = FakeTail.created[0]
    assert first.directory == DEFAULT_LOG_DIR  # empty folder = the usual place

    current["settings"] = replace(current["settings"], game_log_dir=str(tmp_path))
    assert await _wait(lambda: len(FakeTail.created) == 2)
    assert first.finished.is_set()  # the old tail was stopped, not left running
    assert FakeTail.created[1].directory == tmp_path

    current["settings"] = replace(current["settings"], use_game_log=False)
    assert await _wait(lambda: FakeTail.created[1].finished.is_set())

    stop.set()
    await asyncio.wait_for(task, 2)


async def test_cancelling_the_supervisor_stops_its_tail(monkeypatch):
    FakeTail.created.clear()
    monkeypatch.setattr(gamelog_module, "GameLogTail", FakeTail)
    stop = asyncio.Event()
    supervisor = GameLogSupervisor(
        lambda: Settings(use_game_log=True), lambda reason, at: None, poll_s=0.01
    )
    task = asyncio.create_task(supervisor.run(stop))
    assert await _wait(lambda: len(FakeTail.created) == 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert FakeTail.created[0].finished.is_set()  # no tail outlives the worker's loop


# ---- the engine side


CORNERS = [0.20, 0.50, 0.80]
# The real Monza lines and lap length from the stored Ferrari 296 GT3 entry: its S1/S2 split is
# 1949 m and the S2/S3 split 3804 m of a 5793 m lap.
MONZA_LENGTH_M = 5793.0
MONZA_LINES = (0.33644832163172367, 0.6567313191597194)


def _engine(store, boundaries=None, length=LENGTH, **settings):
    """A warmed-up engine on a synthetic track (equal thirds unless ``boundaries`` is given).

    With no ``boundaries`` the track uses equal thirds; pass the real stored lines and length to
    reproduce a field log exactly.
    """
    if boundaries is not None:
        data = TrackData.empty("Monza", "Car A", N_SECTORS)
        data.boundaries = list(boundaries)
        store.save(data)
    results: list = []
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(**{"use_game_log": False, "warmup_laps": 0, **settings}),
        store,
        on_sector=results.append,
        on_message=messages.append,
    )
    driver = Driver(engine, length=length)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    messages.clear()
    return engine, driver, results, messages


def stored_times(store, sector: int) -> list[float]:
    return [r.t for r in store.load("Monza", "Car A", N_SECTORS).sectors[sector]]


def test_a_cut_is_dropped_in_the_sector_where_the_game_reports_it(store):
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # in S2 (1/3..2/3)
    engine.report_infraction("the game reported a cut", driver.t)
    lap = engine._lap_no
    assert (lap, 1) in engine._invalid_sectors
    assert engine.snapshot().sector == 1 and engine.snapshot().pass_flag == "off track"
    assert any("S2 won't count" in m for m in messages)


@pytest.mark.parametrize("reported_at", [0.671, 0.683, 0.716, 0.726])
def test_a_monza_cut_at_ascari_drops_s3_not_the_sector_behind_it(store, reported_at):
    # The field logs from the old build, which trusted the report position, put cuts at 67.1% and
    # 68.3% (Ascari) and the app was told about a cut at 71.6%/72.6% (curve 10, the last Ascari
    # before Parabolica). All are past the 65.67% S2/S3 line, so all are S3. Reading the report
    # back by a fixed 500 m moved them into S2 - the wrong sector on the bar.
    engine, driver, _, messages = _engine(store, boundaries=MONZA_LINES, length=MONZA_LENGTH_M)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=reported_at)
    engine.report_infraction("the game reported a cut", driver.t)

    lap = engine._lap_no
    assert (lap, 2) in engine._invalid_sectors  # S3, where the game reported the cut
    assert (lap, 1) not in engine._invalid_sectors  # not S2, a fixed distance behind it
    assert any("S3" in m and ("won't count" in m or "taken back" in m) for m in messages)
    assert not any("S2" in m for m in messages if "reported a cut" in m)


def test_a_monza_cut_at_lesmo_drops_s2_not_s1(store):
    # 36.3% of the app's lap is Lesmo 1, in S2. A fixed 500 m read-back put it at 27.7%, in S1, and
    # took back the clean S1 run instead of the cut S2 one.
    engine, driver, _, messages = _engine(store, boundaries=MONZA_LINES, length=MONZA_LENGTH_M)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.363)
    engine.report_infraction("the game reported a cut", driver.t)

    lap = engine._lap_no
    assert (lap, 1) in engine._invalid_sectors  # S2, where the game reported the cut
    assert (lap, 0) not in engine._invalid_sectors  # not S1, a fixed distance behind it
    assert any("S2" in m and ("won't count" in m or "taken back" in m) for m in messages)


def test_a_monza_cut_at_ascari_read_late_takes_back_s3_not_s2(store):
    # The same field case, read after the lap has ended and S3's faster run was saved. The run that
    # goes is S3's, the one the cut invalidated - not S2's, which the old read-back blamed.
    engine, driver, _, messages = _engine(store, boundaries=MONZA_LINES, length=MONZA_LENGTH_M)
    s3_before = stored_times(store, 2)
    assert s3_before
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.716)
    cut_at = driver.t
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.717, stop=1.003)  # S3 closes and is saved
    s2_before = stored_times(store, 1)
    assert stored_times(store, 2)[0] < s3_before[0]  # a faster S3 run was stored

    engine.report_infraction("the game reported a cut", cut_at)

    assert stored_times(store, 2) == s3_before  # S3's cut run was taken back, the list restored
    assert stored_times(store, 1) == s2_before  # S2's clean run is kept
    assert any("S3 had its stored run taken back" in m for m in messages)
    assert not any("S2" in m for m in messages if "reported a cut" in m)


def test_a_cut_reported_while_still_in_its_sector_drops_that_sector(store):
    engine, driver, _, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # in S2 (1/3..2/3)
    engine.report_infraction("the game reported a cut", driver.t)
    snap = engine.snapshot()
    assert snap.sector == 1 and snap.pass_flag == "off track"


def test_a_cut_read_late_is_still_dropped_in_the_sector_it_happened_in(store):
    # The game buffers its log, so this cut is read long after it was written - here when the car is
    # already past the 2/3 line. The line carries its own time, so it still lands in the sector it
    # happened in (1/3..2/3), not where the car was when it was read.
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
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.55)  # the cut at 0.55, in S2
    written_at = driver.t
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


def test_a_lap_flag_dropping_just_before_the_line_drops_the_lap_being_ended(store):
    # A cut on the last corner is judged there, just before the line. The flag belongs to the lap
    # that is ending: its S3 goes, not S1 of the lap that starts a moment later.
    engine, driver, _, _ = _engine(store)
    p = driver.lap(CORNERS, speed_fn=lambda p: 215)  # lap A ends: S3 saved
    lap_a = stored_times(store, 2)
    assert lap_a

    driver.lap(CORNERS, speed_fn=lambda p: 215, start=p, stop=p + 0.96, invalid_from=p + 0.95)
    lap = engine._lap_no
    assert (lap, 2) in engine._invalid_sectors  # S3, where the flag fell
    assert (lap, 0) not in engine._invalid_sectors  # not S1 of the lap that follows

    driver.lap(CORNERS, speed_fn=lambda p: 215, start=p + 0.96, stop=p + 1.003)
    assert stored_times(store, 2) == lap_a  # the flagged S3 was not stored


def test_a_cut_from_before_the_kept_history_is_skipped_rather_than_guessed(store):
    # Guessing from the current position would drop whatever sector the car is in now, which is
    # worse than saying nothing: a report older than the kept history is dropped.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.85)
    engine.report_infraction("the game reported a cut", driver.t - 1000.0)
    assert engine.snapshot().pass_flag == ""
    assert not any("reported a cut" in m for m in messages)


def test_the_run_history_is_pruned_with_the_sample_history(store):
    # A report is attributed from the samples, so a run record is only useful while the samples
    # around its crossing are still kept: both expire on the same window.
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.10, 200.0, 0.0)
    now = driver.t
    fresh = _LapRun(SectorRun(30.0, [0.2]), [], now - _HISTORY_S + 1.0)
    stale = _LapRun(SectorRun(31.0, [0.2]), [], now - _HISTORY_S - 1.0)
    engine._lap_runs[(1, 0)] = fresh
    engine._lap_runs[(0, 0)] = stale
    engine._prune_lap_runs()

    assert engine._lap_runs == {(1, 0): fresh}


def test_two_late_reported_cuts_drop_only_their_own_sectors(store):
    # Two cuts in one lap, one in S2 and one in S3. Only those two sectors go; the clean first
    # sector of the lap stays.
    engine, driver, results, _ = _engine(store)
    before = [stored_times(store, i) for i in range(N_SECTORS)]
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.60)  # a cut in S2, just closed and saved
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.61, stop=0.85)  # a cut in S3
    engine.report_infraction("the game reported a cut", driver.t)
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.86, stop=1.003)
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
    assert status[0] is SectorStatus.PENDING  # S1, where the first report was written
    assert status[1] is SectorStatus.PENDING  # S2, where the second was written


def test_a_cut_reported_in_the_frame_that_wraps_the_line_stays_in_the_laps_last_sector(store):
    # A live cut just before the line drops S3 of the lap that is ending. The game's log line for
    # that same cut is read a moment later, with ``at`` inside the telemetry frame that wraps the
    # start/finish line. Both samples of that frame still carry the old lap number, so interpolating
    # across the wrap would return a position just after 0.0 labelled with the old lap: S1 of that
    # lap, a second sector. Backing off to the earlier sample keeps the line in S3, which the live
    # cut already dropped, so one cut still drops one sector.
    engine, driver, _, messages = _engine(store)
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
    at = (crossing_between(t0, p0, t1, p1, 0.0) + t1) / 2
    engine.report_infraction("off track", at)

    assert (lap - 1, 2) in engine._invalid_sectors  # still that lap's S3
    assert (lap - 1, 0) not in engine._invalid_sectors  # not a second sector, its S1
    assert not any("S1" in m and "previous lap" in m for m in messages)


def test_a_live_lap_flag_on_the_crossing_sample_leaves_the_sector_to_the_log(store):
    # The flag goes down between the last sample of a lap and the first one after the line. The
    # live signal has no timestamp, so with the log on it defers: the log's line names the cut's
    # own time and can tell the lap's S3 from the new lap's S1.
    engine, driver, results, _ = _engine(store, boundaries=[1 / 3, 2 / 3], use_game_log=True)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.999)
    driver.feed(0.9998, 215.0, 0.0, valid=True)  # the last sample of the lap
    cut_t = driver.t
    driver.feed(0.0001, 215.0, 0.0, valid=False)  # the line and the flag in one frame
    lap = engine._lap_no  # the new lap
    assert (lap, 0) not in engine._invalid_sectors  # the live flag did not guess S1

    engine.report_infraction("off track", cut_t)
    assert (lap - 1, 2) in engine._invalid_sectors  # the log's time puts it in the old S3
    assert (lap, 0) not in engine._invalid_sectors

    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.0002, stop=1.0001)
    by_sector = {r.sector: r for r in results}
    assert by_sector[0].accepted  # the new lap's first sector still counts


def test_a_cut_read_after_the_line_stays_in_the_new_laps_first_sector(store):
    # The first sample after the start/finish line still carries the old lap number: ``update``
    # appends to the history before it counts the lap up. A line read between that sample and the
    # next therefore belongs to the new lap, and its cut is S1 of the lap being driven, not S1 of
    # the lap that ended.
    engine, driver, _, messages = _engine(store)
    driver.feed(0.001, 200.0, 0.0)  # the frame that crosses the line: still the old lap's number
    lap = engine._lap_no
    before_t, before_lap = driver.t, engine._timeline.last.lap
    driver.feed(0.02, 200.0, 0.0)
    after = engine._timeline.last
    assert before_lap == lap - 1 and after.lap == lap  # the line fell on the earlier sample
    prior_s1 = stored_times(store, 0)

    engine.report_infraction("cut", (before_t + after.t) / 2)

    assert (lap, 0) in engine._invalid_sectors
    assert (lap - 1, 0) not in engine._invalid_sectors
    assert engine.snapshot().pass_flag == "off track"
    assert not any("previous lap" in m for m in messages)
    assert stored_times(store, 0) == prior_s1  # the last lap's stored S1 run is untouched


def test_a_cut_in_a_frame_that_teleports_is_placed_at_the_earlier_sample(store):
    # 0.30 -> 0.45 in one frame is a teleport, past the engine's jump threshold: the car never drove
    # the track between them. Interpolating the midpoint would place the cut at 0.375, in S2, while
    # the car was still at 0.30 in S1 (equal splits: 0 .. 1/3 .. 2/3). The earlier sample is used.
    engine, driver, _, messages = _engine(store)
    driver.feed(0.30, 200.0, 0.0)
    t_before = driver.t
    driver.feed(0.45, 200.0, 0.0)
    t_after = driver.t
    engine.report_infraction("off track", (t_before + t_after) / 2)

    assert any("S1" in m and ("won't count" in m or "taken back" in m) for m in messages)
    assert not any("S2" in m for m in messages)


def test_a_cut_in_a_sector_that_was_not_saved_still_shows_as_not_counted(store):
    # The cut sector's time may already be slower than the best, so there is no run to take back;
    # the sector must still stop counting.
    engine, driver, _, messages = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 195, stop=0.60)  # in S2, slower than the warm-up runs
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

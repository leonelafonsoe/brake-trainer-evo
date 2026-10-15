from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.gamelog import GameLogTail, LogState, parse_line

from .conftest import Driver

PLAYER = "0a1b2c3d-1111-2222-3333-444455556666"
AI = "ffffffff-aaaa-bbbb-cccc-000011112222"
CONNECT = (
    "[2026-10-14 21:00:00.100] [network] [info] 76561198000000001 connected on car "
    f"ferrari_296_gtb, with new carId {PLAYER}"
)
AI_CONNECT = (
    f"[2026-10-14 21:00:00.200] [network] [info] 0 connected on car bmw_m4, with new carId {AI}"
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


def test_a_violation_is_all_four_tyres_out_two_metres_or_more_for_the_player():
    state = player_state()
    assert parse_line(limits(PLAYER, 4, 2.62), state)
    assert parse_line(limits(PLAYER, 4, 2.0), state)
    assert not parse_line(limits(PLAYER, 4, 1.4), state)  # brief excursion: tolerated
    assert not parse_line(limits(PLAYER, 3, 3.0), state)  # not all four tyres
    assert not parse_line(limits(PLAYER, 4, 12.52), state)  # teleported to the pits
    assert not parse_line(limits(AI, 4, 3.0), state)  # someone else's car
    assert not parse_line("[x] some other line", state)


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


async def test_tail_reports_only_new_violations_and_follows_newer_logs(tmp_path: Path):
    old = tmp_path / "old.txt"
    old.write_text("\n".join([CONNECT, limits(PLAYER, 4, 3.0)]) + "\n", encoding="utf-8")
    hits: list[int] = []
    tail = GameLogTail(tmp_path, lambda: hits.append(1), poll_s=0.01, rescan_s=0.02)
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    await asyncio.sleep(0.3)
    assert hits == []  # history is not replayed

    with old.open("a", encoding="utf-8") as fh:
        fh.write(limits(AI, 4, 3.0) + "\n")  # not the player
        fh.write(limits(PLAYER, 4, 1.0) + "\n")  # too short
        line = limits(PLAYER, 4, 2.7)
        fh.write(line[:30])  # a line written in two pieces
        fh.flush()
        await asyncio.sleep(0.1)
        assert hits == []
        fh.write(line[30:] + "\n")
    assert await _wait(lambda: len(hits) == 1)

    new = tmp_path / "new.txt"  # the game was restarted
    new.write_text(CONNECT + "\n" + limits(PLAYER, 4, 5.0) + "\n", encoding="utf-8")
    os.utime(new, (time.time() + 5, time.time() + 5))
    await asyncio.sleep(0.3)
    assert len(hits) == 1  # its first content is history too
    with new.open("a", encoding="utf-8") as fh:
        fh.write(limits(PLAYER, 4, 3.3) + "\n")
    assert await _wait(lambda: len(hits) == 2)
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_tail_without_a_log_folder_just_says_so(tmp_path: Path):
    messages: list[str] = []
    tail = GameLogTail(
        tmp_path / "missing", lambda: None, messages.append, poll_s=0.01, rescan_s=0.01
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
    results: list = []
    engine = BrakeEngine(
        Settings(n_sectors=5, warmup_laps=0, **settings), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    return engine, driver, results


def test_a_reported_violation_drops_the_sector_in_progress(store):
    engine, driver, results = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.3)  # half-way through S2
    engine.report_violation()
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.3, stop=1.003)
    by_sector = {r.sector: r for r in results}
    assert by_sector[1].duration is None and "off limits" in by_sector[1].note
    assert by_sector[2].accepted  # the next sector is unaffected


def test_a_violation_reported_just_after_a_sector_closed_takes_it_back(store):
    engine, driver, _ = _engine(store)
    old_best = store.load("Monza", "Car A", 5).sectors[1][0].t
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.402)  # S2 just closed and was saved
    assert store.load("Monza", "Car A", 5).sectors[1][0].t < old_best
    engine.report_violation()
    assert store.load("Monza", "Car A", 5).sectors[1][0].t == old_best  # taken back


def test_a_late_report_does_not_touch_an_older_sector(store):
    engine, driver, _ = _engine(store)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.45)  # S2 closed seconds ago
    saved_best = store.load("Monza", "Car A", 5).sectors[1][0].t
    engine.report_violation()
    assert store.load("Monza", "Car A", 5).sectors[1][0].t == saved_best


def test_violations_are_ignored_when_invalid_sectors_are_not_skipped(store):
    engine, driver, results = _engine(store, skip_invalid_sectors=False)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.3)
    engine.report_violation()
    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.3, stop=1.003)
    assert {r.sector: r for r in results}[1].accepted


def test_snapshot_shows_the_current_problem(store):
    engine, driver, _ = _engine(store)
    driver.lap(CORNERS, stop=0.3)
    engine.report_violation()
    driver.feed(0.31, 150.0, 0.0)
    assert engine.snapshot().pass_flag == "off limits"


@pytest.mark.parametrize("name", ["use_game_log", "game_log_dir"])
def test_game_log_settings_exist(name):
    assert hasattr(Settings(), name)

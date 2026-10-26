from __future__ import annotations

import logging

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine, race_cut_active

from .conftest import Driver
from .engine_helpers import CORNERS


def _fast_lap_results(store, **lap_kwargs):
    results = []
    settings = Settings(use_game_log=False, warmup_laps=0)
    engine = BrakeEngine(settings, store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    best_before = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, **lap_kwargs)  # faster everywhere
    best_after = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    return {r.sector: r for r in results}, best_before, best_after


def test_the_lap_flag_drops_the_sector_where_it_fell(store):
    # The flag falls in the middle of S2 (1/3..2/3). That is the sector the game judged, so S2 is
    # the one that must not count; S1 was already driven cleanly and keeps its faster run.
    by_sector, before, after = _fast_lap_results(store, invalid_from=0.52)
    assert by_sector[1].duration is None and "invalidated" in by_sector[1].note
    assert after[1] == before[1]  # the faster-but-invalid sector was not stored
    assert by_sector[0].accepted and after[0] < before[0]  # the sector before is kept
    assert by_sector[2].accepted and after[2] < before[2]  # later sectors were driven cleanly


def test_a_lap_flag_in_s3_does_not_take_back_the_s2_run_before_it(store):
    # The flag falls in S3. The sector that must not count is S3; S2's faster, clean run stays.
    by_sector, before, after = _fast_lap_results(store, invalid_from=0.70)
    assert by_sector[2].duration is None and "invalidated" in by_sector[2].note
    assert after[2] == before[2]  # the faster-but-invalid S3 was not stored
    assert by_sector[1].accepted and after[1] < before[1]  # S2's clean run is kept


def test_a_lap_flag_on_the_frame_that_crosses_the_line_drops_the_lap_being_ended(store):
    # The flag goes down between the last sample of a lap and the first one after the line. The
    # position has already moved into S1 of the new lap, but the car has not driven that sector
    # yet: the flag belongs to the S3 that just ended.
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    before = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    results.clear()

    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=0.999)
    driver.feed(0.9998, 215.0, 0.0, valid=True)  # the last sample of the lap
    driver.feed(0.0001, 215.0, 0.0, valid=False)  # the line and the flag in one frame
    lap = engine._lap_no - 1  # the lap that just ended
    assert (lap, 2) in engine._invalid_sectors  # its S3, where the cut was
    assert (lap + 1, 0) not in engine._invalid_sectors  # not S1 of the new lap
    after = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    assert after[2] == before[2]  # the faster S3 was taken back

    driver.lap(CORNERS, speed_fn=lambda p: 215, start=0.0002, stop=1.0001)
    by_sector = {r.sector: r for r in results}
    assert by_sector[0].accepted  # the new lap's S1 is clean


def test_sector_with_a_race_cut_is_not_saved(store):
    by_sector, before, after = _fast_lap_results(store, cut=(0.45, 0.46))
    assert by_sector[1].duration is None and "off track" in by_sector[1].note
    assert after[1] == before[1]
    assert after[0] < before[0] and after[2] < before[2]


def test_a_lap_that_cannot_count_anyway_does_not_name_its_flag(store):
    # Session started from the pits: the game invalidates the lap the car is already on. That lap is
    # a warm-up lap and was never going to count, so the overlay says so rather than opening the
    # session by blaming a flag that changes nothing.
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store)
    driver = Driver(engine)
    driver.feed(0.0, 100.0, 0.0)
    driver.feed(0.05, 100.0, 0.0, valid=False)  # the game invalidates the lap

    snap = engine.snapshot()
    assert snap.warming_up and snap.warmup_laps_left == 1
    assert snap.pass_flag == ""


def test_a_second_off_is_caught_by_the_games_race_cut_signal(store):
    # The one-shot lap flag drops in S1. The race-cut pair the game fills in for a second
    # off-track in S2 lets that sector be dropped too.
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=1.003, invalid_from=0.3, cut=(0.50, 0.51))
    by_sector = {r.sector: r for r in results}
    assert "invalidated" in by_sector[0].note
    assert by_sector[1].duration is None and "off track" in by_sector[1].note
    assert by_sector[2].accepted  # the sector without an off-track is kept


@pytest.mark.parametrize(
    ("gained", "deadline", "active"),
    [
        (0, 0, False),
        (1, 0, True),
        (320, 0, True),
        (320, 150, True),
        (60_000, 5_000, True),
        (0, 150, False),  # a give-back distance with no time gained is not a cut
        (-1, 150, False),
        (60_001, 150, False),
        (320, -1, False),
        (320, 5_001, False),
    ],
)
def test_race_cut_active_only_accepts_a_plausible_pair(gained, deadline, active):
    assert race_cut_active(gained, deadline) is active


@pytest.mark.parametrize(("gained", "deadline"), [(10**6, 120), (320, 6_000), (0, 120)])
def test_an_implausible_race_cut_pair_cannot_drop_a_sector(store, gained, deadline):
    # A shifted graphics block decodes to an arbitrary pair. A positive gain drops a sector, so an
    # implausible one must be read as no cut even when a Sample carries it straight to the engine.
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    driver.feed(0.10, 150.0, 0.0)
    for p in (0.11, 0.12, 0.13):
        driver.feed(p, 150.0, 0.0, cut_gained_ms=gained, cut_deadline_m=deadline)
    assert not any("Off the track" in m for m in messages)
    assert engine.snapshot().pass_flag == ""


def test_one_race_cut_is_flagged_once(store):
    # The deadline counts down for the rest of the off-track; that must not flag the sector again.
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    driver.feed(0.10, 150.0, 0.0)
    for p in (0.11, 0.12, 0.13, 0.14):
        driver.feed(p, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)
    for p in (0.15, 0.16):
        driver.feed(p, 150.0, 0.0)  # cut cleared
    assert sum("Off the track" in m for m in messages) == 1
    assert engine.snapshot().pass_flag == "off track"


def test_a_later_race_cut_is_flagged_again(store):
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    driver.feed(0.10, 150.0, 0.0)
    driver.feed(0.30, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)
    driver.feed(0.31, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=100)
    driver.feed(0.32, 150.0, 0.0)  # cleared
    driver.feed(0.60, 150.0, 0.0, cut_gained_ms=180, cut_deadline_m=90)  # a second, later cut
    assert sum("Off the track" in m for m in messages) == 2


def test_a_second_race_cut_with_the_same_gained_time_is_flagged_again(store):
    # The deadline counts down while one cut is being given back. A new cut grows it again; that is
    # a new cut even when it happens to gain exactly the same time as the one before.
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    driver.feed(0.10, 150.0, 0.0)
    for p, deadline in ((0.30, 120), (0.31, 110), (0.32, 100)):
        driver.feed(p, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=deadline)
    for step in range(33, 61):  # still the same cut, crossing into S2 with the deadline counting
        driver.feed(step / 100, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=100)
    driver.feed(0.61, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)  # a second cut, same gain

    assert sum("Off the track" in m for m in messages) == 2
    assert engine.snapshot().sector == 1 and engine.snapshot().pass_flag == "off track"


def _warnings_engine(store):
    # With the game log read (the default) a cut is always pinned to its own sector, so the
    # fallback warning only exists for when there is no per-cut source: the log is switched off.
    warnings: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_warning=warnings.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    return driver, warnings


def test_a_cut_is_reported_as_not_visible_in_memory(store):
    # The game invalidates the lap, but it reported no off-track event: a cut it judged from
    # something it does not expose.
    driver, warnings = _warnings_engine(store)
    driver.lap(CORNERS, invalid_from=0.5, stop=1.003)
    assert len(warnings) == 1 and "no race cut" in warnings[0]


def test_no_cut_warning_when_a_race_cut_was_seen_first(store):
    driver, warnings = _warnings_engine(store)
    driver.lap(
        CORNERS,
        invalid_from=0.5,
        cut=(0.45, 0.46),  # the race-cut pair is up before the lap flag drops
        stop=1.003,
    )
    assert warnings == []


def test_no_cut_warning_for_a_lap_already_invalid_when_the_app_starts(store):
    # The first sample can land on a lap the app never saw being invalidated: not a cut it saw.
    warnings: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_warning=warnings.append
    )
    driver = Driver(engine)
    driver.feed(0.55, 150.0, 0.0, valid=False)
    driver.feed(0.56, 150.0, 0.0, valid=False)
    assert warnings == []
    assert engine.snapshot().pass_flag == "lap invalidated"


def test_a_lap_flag_on_a_warm_up_lap_is_not_announced(store):
    # Out of the pits the game invalidates the lap it began in, because it did: but that lap is the
    # warm-up one, so the drop changes nothing and the app does not open the session by telling the
    # driver that a sector it was going to skip anyway will not count.
    messages: list[str] = []
    warnings: list[str] = []
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1),
        store,
        on_message=messages.append,
        on_warning=warnings.append,
        on_sector=results.append,
    )
    driver = Driver(engine)
    driver.lap(CORNERS, invalid_from=0.05, stop=1.003)

    assert not any(m.startswith("The game invalidated the lap") for m in messages)
    assert warnings == []  # and no "the game saw no off-track" warning for it either
    # The reason is still on the sector's own result, where the driver looks for it.
    by_sector = {r.sector: r for r in results}
    assert by_sector[0].note == "not counted · warm-up lap"


def test_a_lap_flag_on_a_sector_that_would_count_is_announced(store):
    # The sector was clean and going to count, so the drop is news: the driver is told, and told
    # which sector it takes out.
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    for _ in range(4):  # the equal splits settle after three laps, so passes count from then on
        driver.lap(CORNERS)
    messages.clear()
    driver.lap(CORNERS, start=0.0001, stop=0.30)  # a clean pass, in the first sector
    driver.lap(CORNERS, start=0.31, stop=0.40, invalid_from=0.32)

    said = [m for m in messages if m.startswith("The game invalidated the lap")]
    assert len(said) == 1 and "S1" in said[0]


def test_snapshot_reports_why_the_sector_will_not_count(store):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    Driver(engine).feed(0.65, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)
    assert engine.snapshot().pass_flag == "off track"


def test_verbose_logging_traces_the_track_limit_signals(store, caplog):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    driver = Driver(engine)
    with caplog.at_level(logging.DEBUG, logger="brake_trainer.engine"):
        driver.feed(0.10, 150.0, 0.0)
        driver.feed(0.13, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)
        driver.feed(0.14, 150.0, 0.0)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "race_cut up" in text and "gained=250 ms" in text
    assert "race_cut clear" in text
    assert "lap_valid None -> True" in text

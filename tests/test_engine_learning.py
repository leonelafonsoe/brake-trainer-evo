from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from brake_trainer.config import Settings
from brake_trainer.engine import N_SECTORS, BrakeEngine, build_zones
from brake_trainer.models import CueKind, SectorResult, SectorRun
from brake_trainer.models import SectorStatus as S

from .conftest import LENGTH, Driver
from .engine_helpers import CORNERS


def _fixed_speed(value: float) -> Callable[[float], float]:
    def speed(_pos: float) -> float:
        return value

    return speed


def test_build_zones_median_and_wraparound():
    runs = [
        [SectorRun(30, [0.0001]), SectorRun(30, [0.0003]), SectorRun(31, [0.0002])],
        [SectorRun(30, [0.2000]), SectorRun(30, [0.2004]), SectorRun(31, [0.2002])],
        [SectorRun(30, [0.9998]), SectorRun(30, [0.9997]), SectorRun(31, [0.9999])],
    ]
    zones = build_zones(runs, cluster_m=40, length_m=LENGTH)
    # the corner at the start/finish line was seen from both sides of it: one zone, not two
    assert len(zones) == 2
    assert any(abs(z - 0.2002) < 1e-6 for z in zones)


def test_corner_needs_half_of_the_runs():
    runs = [[SectorRun(30, [0.2]), SectorRun(30, []), SectorRun(30, [])]]
    assert build_zones(runs, 40, LENGTH) == []


def test_learns_zones_and_cues_after_clean_sectors(make_engine, cues):
    driver = Driver(make_engine())
    for _ in range(4):
        driver.lap(CORNERS, jitter=0.001)
    zones = driver.engine.snapshot().zones
    assert len(zones) == 3
    assert [round(z, 2) for z in zones] == CORNERS
    assert CueKind.WARN in cues


def test_faster_sector_is_saved_before_a_crash(make_engine, store):
    engine = make_engine()
    driver = Driver(engine)
    for _ in range(3):
        driver.lap(CORNERS)
    # fast first sector, then a teleport back to the pits area (crash/reset) in sector 3
    p = driver.lap(CORNERS, speed_fn=lambda x: 215 if x < 0.2 else 200, stop=0.45)
    driver.feed(0.9, 0.0, 0.0)  # reset somewhere else
    stored = store.load("Monza", "Car A", 3)
    best_s1 = stored.sectors[0][0].t
    assert best_s1 < stored.sectors[1][0].t * 0.95 or best_s1 < 30  # faster S1 persisted
    assert p < 0.5


def test_pit_lap_is_not_counted(store):
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    p = 0.0001
    while p < 1.0:
        driver.feed(p, 100.0, 0.0, pit=True)
        p += 100 / 3.6 * (1 / 30) / LENGTH
    assert results and all(r.duration is None for r in results)


def test_new_car_borrows_reference_then_switches(make_engine, store):
    a = Driver(make_engine(), car="Car A")
    for _ in range(4):
        a.lap(CORNERS)
    a.engine.flush()

    b = Driver(make_engine(), car="Car B")
    b.feed(0.0001, 100, 0.0)
    snap = b.engine.snapshot()
    assert snap.reference_car == "Car A"
    assert len(snap.reference_sectors) == 3  # the sectors that hold a borrowed braking point
    assert len(snap.zones) == 3

    shifted = [c - 0.01 for c in CORNERS]
    for _ in range(4):
        b.lap(shifted)
    snap = b.engine.snapshot()
    assert snap.reference_sectors == ()
    assert [round(z, 2) for z in snap.zones] == [round(c, 2) for c in shifted]


def test_settings_change_rebuilds_zones(make_engine):
    driver = Driver(make_engine())
    for _ in range(3):
        driver.lap(CORNERS)
    assert driver.engine.snapshot().zones
    driver.engine.apply_settings(
        Settings(use_game_log=False, warmup_laps=0, min_peak=1.0)
    )  # nothing qualifies later
    driver.feed(0.3, 150, 0.0)
    assert driver.engine.snapshot().n_sectors == N_SECTORS


def test_a_new_reference_car_takes_effect_without_a_session_change(make_engine):
    a = Driver(make_engine(), car="Car A")
    for _ in range(4):
        a.lap(CORNERS)
    a.engine.flush()
    b = Driver(make_engine(), car="Car B")
    for _ in range(4):
        b.lap([c - 0.03 for c in CORNERS])
    b.engine.flush()

    c = Driver(make_engine(reference_car="Car A"), car="Car C")
    c.feed(0.0001, 100.0, 0.0)
    assert c.engine.snapshot().reference_car == "Car A"

    c.engine.apply_settings(replace(c.engine.settings, reference_car="Car B"))

    snap = c.engine.snapshot()  # no further sample: the change is already live
    assert snap.reference_car == "Car B"
    assert [round(z, 2) for z in snap.zones] == [round(x - 0.03, 2) for x in CORNERS]


def test_reducing_top_runs_keeps_only_the_fastest_stored_runs(store):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0, kept_runs=5), store)
    driver = Driver(engine)
    for speed in (205, 200, 195, 190, 185, 180, 175):
        driver.lap(CORNERS, speed_fn=_fixed_speed(speed))
    engine.flush()
    before = store.load("Monza", "Car A", N_SECTORS)
    assert all(len(runs) == 5 for runs in before.sectors)
    fastest = [sorted(r.t for r in runs) for runs in before.sectors]

    engine.apply_settings(replace(engine.settings, kept_runs=2))

    after = store.load("Monza", "Car A", N_SECTORS)
    assert all(len(runs) == 2 for runs in after.sectors)
    assert [[r.t for r in runs] for runs in after.sectors] == [times[:2] for times in fastest]
    assert engine.snapshot().zones  # rebuilt from what is left


def test_turning_the_game_log_off_stops_waiting_for_its_sector_lines(store):
    messages: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=True, warmup_laps=0), store, on_message=messages.append
    )
    driver = Driver(engine)
    driver.feed(0.0001, 100.0, 0.0)
    assert engine._learning_lines  # a fresh entry waits for the game's own lines

    engine.apply_settings(replace(engine.settings, use_game_log=False))

    assert not engine._learning_lines
    assert any("turned off" in m for m in messages)
    assert engine.snapshot().boundaries == (0.0, 1 / 3, 2 / 3, 1.0)

    engine.apply_settings(replace(engine.settings, use_game_log=True))
    assert engine._learning_lines  # nothing stored yet, so it can wait again


def test_sector_colours_follow_the_results(make_engine):
    driver = Driver(make_engine())
    for _ in range(4):  # the very first sector pass starts mid-sector and doesn't count
        driver.lap(CORNERS)
    slow = driver.lap(CORNERS, speed_fn=lambda p: 190)
    assert slow > 1.0
    assert set(driver.engine.snapshot().sector_status) == {S.SLOWER}  # slower than 3 kept runs
    driver.lap(CORNERS, speed_fn=lambda p: 215)
    assert set(driver.engine.snapshot().sector_status) == {S.BEST}  # fastest ever
    statuses = driver.engine.snapshot().sector_status
    assert len(statuses) == N_SECTORS


def test_a_sector_result_is_measured_against_the_best_it_compares_with(store):
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)

    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 195)  # slower than the three kept runs
    slow = {r.sector: r for r in results}
    assert all(r.status is S.SLOWER for r in slow.values())
    for r in slow.values():
        assert r.best is not None and r.delta is not None
        assert r.duration is not None
        assert r.delta > 0 and abs(r.delta - (r.duration - r.best)) < 1e-9

    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215)  # beats everything kept
    fast = {r.sector: r for r in results}
    assert all(r.status is S.BEST for r in fast.values())
    for r in fast.values():
        assert r.previous_best is not None and r.delta is not None
        assert r.duration is not None
        assert r.delta < 0 and abs(r.delta - (r.duration - r.previous_best)) < 1e-9


def test_progress_through_current_sector(make_engine):
    driver = Driver(make_engine())
    driver.feed(0.50, 100.0, 0.0)  # sector 2 spans 1/3..2/3 -> halfway
    snap = driver.engine.snapshot()
    assert snap.sector == 1 and abs(snap.sector_progress - 0.5) < 1e-6


def test_learning_off_keeps_marks_but_still_cues_and_colours(make_engine, store, cues):
    driver = Driver(make_engine())
    for _ in range(4):
        driver.lap(CORNERS)
    before = store.load("Monza", "Car A", 3).to_dict()
    zones_before = driver.engine.snapshot().zones

    driver.engine.apply_settings(replace(driver.engine.settings, learning_enabled=False))
    cues.clear()
    for _ in range(3):
        driver.lap([c + 0.02 for c in CORNERS], speed_fn=lambda p: 215)  # faster, braking elsewhere

    assert store.load("Monza", "Car A", 3).to_dict() == before  # nothing saved
    assert driver.engine.snapshot().zones == zones_before  # marks unchanged
    assert CueKind.WARN in cues  # cues keep working
    assert S.BEST in driver.engine.snapshot().sector_status  # colours still shown


def test_sector_straddling_a_pause_is_not_stored(store):
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()

    engine.apply_settings(replace(engine.settings, learning_enabled=False))
    driver.lap(CORNERS, stop=0.5)  # paused up to the middle of sector 2
    engine.apply_settings(replace(engine.settings, learning_enabled=True))
    driver.lap(CORNERS, start=0.5, stop=1.0001)  # resumed: sector 2 was only half learned

    counted = {r.sector: r for r in results}
    assert counted[1].duration is None and "paused" in counted[1].note
    assert counted[2].duration is not None  # fully learned sectors count again


def test_first_lap_after_leaving_the_pits_is_not_learned(store):
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1), store, on_sector=results.append
    )
    driver = Driver(engine)
    driver.lap(CORNERS, stop=1.003)  # lap 1: warm-up, ends just past the line
    assert store.load("Monza", "Car A", 3).total_runs() == 0
    assert any("warm-up" in r.note for r in results)
    assert engine.snapshot().warming_up is False  # warm-up over once the line is crossed

    driver.lap(CORNERS)  # lap 2: counts
    learned = store.load("Monza", "Car A", 3).total_runs()
    assert learned > 0

    for _ in range(5):  # pit stop: fresh tyres, warm up again
        driver.feed(0.3, 50.0, 0.0, pit=True)
    assert engine.snapshot().warming_up is True
    driver.lap(CORNERS)
    assert store.load("Monza", "Car A", 3).total_runs() == learned  # nothing new from that lap


def test_warm_up_laps_can_be_switched_off_and_cues_still_play(store, cues):
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_cue=lambda kind: cues.append(kind)
    )
    driver = Driver(engine)
    driver.lap(CORNERS)
    assert store.load("Monza", "Car A", 3).total_runs() > 0

    other = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=1), store, on_cue=lambda kind: cues.append(kind)
    )
    cues.clear()
    Driver(other).lap(CORNERS)  # warm-up lap on a known track: cues still play
    assert CueKind.WARN in cues

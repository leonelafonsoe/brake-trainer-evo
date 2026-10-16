from __future__ import annotations

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine, build_zones, sector_count
from brake_trainer.models import CueKind, SectorRun

from .conftest import LENGTH, Driver

CORNERS = [0.20, 0.50, 0.80]


def test_sector_count_scales_with_length_and_clamps():
    st = Settings()
    assert sector_count(st, 1800) == 3  # clamped up
    assert sector_count(st, 5800) == 6
    assert sector_count(st, 20800) == 8  # clamped down
    assert sector_count(Settings(n_sectors=4), 20800) == 4


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
    driver = Driver(make_engine(n_sectors=5))
    for _ in range(4):
        driver.lap(CORNERS, jitter=0.001)
    zones = driver.engine.snapshot().zones
    assert len(zones) == 3
    assert [round(z, 2) for z in zones] == CORNERS
    assert CueKind.WARN in cues


def test_faster_sector_is_saved_before_a_crash(make_engine, store):
    engine = make_engine(n_sectors=5)
    driver = Driver(engine)
    for _ in range(3):
        driver.lap(CORNERS)
    # fast first sector, then a teleport back to the pits area (crash/reset) in sector 3
    p = driver.lap(CORNERS, speed_fn=lambda x: 215 if x < 0.2 else 200, stop=0.45)
    driver.feed(0.9, 0.0, 0.0)  # reset somewhere else
    stored = store.load("Monza", "Car A", 5)
    best_s1 = stored.sectors[0][0].t
    assert best_s1 < stored.sectors[1][0].t * 0.95 or best_s1 < 30  # faster S1 persisted
    assert p < 0.5


def test_pit_lap_is_not_counted(store):
    results = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    p = 0.0001
    while p < 1.0:
        driver.feed(p, 100.0, 0.0, pit=True)
        p += 100 / 3.6 * (1 / 30) / LENGTH
    assert results and all(r.duration is None for r in results)


def test_new_car_borrows_reference_then_switches(make_engine, store):
    a = Driver(make_engine(n_sectors=5), car="Car A")
    for _ in range(4):
        a.lap(CORNERS)
    a.engine.flush()

    b = Driver(make_engine(n_sectors=5), car="Car B")
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
    driver = Driver(make_engine(n_sectors=5))
    for _ in range(3):
        driver.lap(CORNERS)
    assert driver.engine.snapshot().zones
    driver.engine.apply_settings(
        Settings(n_sectors=5, warmup_laps=0, min_peak=1.0)
    )  # nothing qualifies later
    driver.feed(0.3, 150, 0.0)
    assert driver.engine.snapshot().n_sectors == 5


def test_group_sizes():
    from brake_trainer.models import group_sizes

    assert group_sizes(0) == ()
    assert group_sizes(1) == (1,)
    assert group_sizes(2) == (1, 1)
    assert group_sizes(3) == (1, 1, 1)
    assert group_sizes(6) == (2, 2, 2)
    assert group_sizes(8) == (3, 3, 2)
    assert sum(group_sizes(7)) == 7


def test_sector_colours_follow_the_results(make_engine):
    from brake_trainer.models import SectorStatus as S

    driver = Driver(make_engine(n_sectors=5))
    for _ in range(4):  # the very first sector pass starts mid-sector and doesn't count
        driver.lap(CORNERS)
    slow = driver.lap(CORNERS, speed_fn=lambda p: 190)
    assert slow > 1.0
    assert set(driver.engine.snapshot().sector_status) == {S.SLOWER}  # slower than 3 kept runs
    driver.lap(CORNERS, speed_fn=lambda p: 215)
    assert set(driver.engine.snapshot().sector_status) == {S.BEST}  # fastest ever
    statuses = driver.engine.snapshot().sector_status
    assert len(statuses) == 5


def test_progress_through_current_sector(make_engine):
    driver = Driver(make_engine(n_sectors=5))
    driver.feed(0.30, 100.0, 0.0)  # sector 1 spans 0.2..0.4 -> halfway
    snap = driver.engine.snapshot()
    assert snap.sector == 1 and abs(snap.sector_progress - 0.5) < 1e-6


def test_learning_off_keeps_marks_but_still_cues_and_colours(make_engine, store, cues):
    from dataclasses import replace

    from brake_trainer.models import SectorStatus as S

    driver = Driver(make_engine(n_sectors=5))
    for _ in range(4):
        driver.lap(CORNERS)
    before = store.load("Monza", "Car A", 5).to_dict()
    zones_before = driver.engine.snapshot().zones

    driver.engine.apply_settings(replace(driver.engine.settings, learning_enabled=False))
    cues.clear()
    for _ in range(3):
        driver.lap([c + 0.02 for c in CORNERS], speed_fn=lambda p: 215)  # faster, braking elsewhere

    assert store.load("Monza", "Car A", 5).to_dict() == before  # nothing saved
    assert driver.engine.snapshot().zones == zones_before  # marks unchanged
    assert CueKind.WARN in cues  # cues keep working
    assert S.BEST in driver.engine.snapshot().sector_status  # colours still shown


def test_sector_straddling_a_pause_is_not_stored(store):
    from dataclasses import replace

    results = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()

    engine.apply_settings(replace(engine.settings, learning_enabled=False))
    driver.lap(CORNERS, stop=0.5)  # paused up to the middle of sector 3
    engine.apply_settings(replace(engine.settings, learning_enabled=True))
    driver.lap(CORNERS, start=0.5, stop=1.0001)  # resumed: sector 3 was only half learned

    counted = {r.sector: r for r in results}
    assert counted[2].duration is None and "paused" in counted[2].note
    assert counted[3].duration is not None  # fully learned sectors count again


def _fast_lap_results(store, **lap_kwargs):
    results = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    best_before = [runs[0].t for runs in store.load("Monza", "Car A", 5).sectors]
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, **lap_kwargs)  # faster everywhere
    best_after = [runs[0].t for runs in store.load("Monza", "Car A", 5).sectors]
    return {r.sector: r for r in results}, best_before, best_after


def test_sector_where_the_lap_was_invalidated_is_not_saved(store):
    # lap invalidated half-way through sector 3 (index 2: 0.4..0.6)
    by_sector, before, after = _fast_lap_results(store, invalid_from=0.5)
    assert by_sector[2].duration is None and "invalidated" in by_sector[2].note
    assert after[2] == before[2]  # the faster-but-invalid sector was not stored
    assert by_sector[1].accepted and after[1] < before[1]  # the sector before is kept
    assert by_sector[3].accepted and after[3] < before[3]  # later sectors were driven cleanly


def test_sector_with_all_tyres_off_track_is_not_saved(store):
    by_sector, before, after = _fast_lap_results(store, off_track=(0.45, 0.46))
    assert by_sector[2].duration is None and "off track" in by_sector[2].note
    assert after[2] == before[2]
    assert after[1] < before[1] and after[3] < before[3]


def test_validity_checks_can_be_switched_off(store):
    results = []
    settings = Settings(n_sectors=5, warmup_laps=0, skip_invalid_sectors=False, max_tyres_out=0)
    engine = BrakeEngine(settings, store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(3):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(CORNERS, invalid_from=0.5, off_track=(0.45, 0.46))
    assert all(r.duration is not None for r in results if r.sector in (1, 2, 3))


def test_first_lap_after_leaving_the_pits_is_not_learned(store):
    results = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store, on_sector=results.append)
    driver = Driver(engine)
    driver.lap(CORNERS, stop=1.003)  # lap 1: warm-up, ends just past the line
    assert store.load("Monza", "Car A", 5).total_runs() == 0
    assert any("warm-up" in r.note for r in results)
    assert engine.snapshot().warming_up is False  # warm-up over once the line is crossed

    driver.lap(CORNERS)  # lap 2: counts
    learned = store.load("Monza", "Car A", 5).total_runs()
    assert learned > 0

    for _ in range(5):  # pit stop: fresh tyres, warm up again
        driver.feed(0.3, 50.0, 0.0, pit=True)
    assert engine.snapshot().warming_up is True
    driver.lap(CORNERS)
    assert store.load("Monza", "Car A", 5).total_runs() == learned  # nothing new from that lap


def test_warm_up_laps_can_be_switched_off_and_cues_still_play(store, cues):
    engine = BrakeEngine(
        Settings(n_sectors=5, warmup_laps=0), store, on_cue=lambda kind: cues.append(kind)
    )
    driver = Driver(engine)
    driver.lap(CORNERS)
    assert store.load("Monza", "Car A", 5).total_runs() > 0

    other = BrakeEngine(
        Settings(n_sectors=5, warmup_laps=1), store, on_cue=lambda kind: cues.append(kind)
    )
    cues.clear()
    Driver(other).lap(CORNERS)  # warm-up lap on a known track: cues still play
    assert CueKind.WARN in cues


def _inside_a_braking_zone(pos, zones):
    from brake_trainer.engine import _CORNER_SPAN_M, _LEAD_SPAN_M

    for z in zones:
        past = ((pos - z) % 1.0) * LENGTH
        if past <= _CORNER_SPAN_M or LENGTH - past <= _LEAD_SPAN_M:
            return True
    return False


def test_snapped_sector_lines_stay_out_of_braking_zones():
    from brake_trainer.engine import snap_boundaries

    zones = [0.20, 0.45, 0.80]  # two corners sit exactly on equal-split lines (n=5)
    lines = snap_boundaries(5, zones, LENGTH)
    assert len(lines) == 4 and lines == sorted(lines)
    assert not any(_inside_a_braking_zone(p, zones) for p in lines)
    assert snap_boundaries(5, [], LENGTH) == [0.2, 0.4, 0.6, 0.8]  # nothing known: equal splits


def test_sector_lines_are_surveyed_on_the_warm_up_lap_and_reused(store):
    corners = [0.20, 0.50, 0.80]  # 0.20 and 0.80 sit on the equal-split lines
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store)
    driver = Driver(engine)
    assert engine.snapshot().boundaries == ()
    driver.lap(corners, stop=1.003)  # the warm-up lap
    lines = list(engine.snapshot().boundaries[1:-1])
    assert lines != [0.2, 0.4, 0.6, 0.8]
    assert not any(_inside_a_braking_zone(p, corners) for p in lines)
    assert store.load("Monza", "Car A", 5).boundaries == lines  # persisted

    for _ in range(4):
        driver.lap(corners, jitter=0.002)
    zones = engine.snapshot().zones
    assert all(any(abs(z - c) < 0.01 for z in zones) for c in corners)  # every corner is learned
    engine.flush()

    other = Driver(BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store), car="Car B")
    other.feed(0.3, 100.0, 0.0)
    assert list(other.engine.snapshot().boundaries[1:-1]) == lines  # a new car shares them


def test_partial_first_lap_does_not_place_sector_lines(store):
    corners = [0.20, 0.50, 0.80]
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store)
    driver = Driver(engine)
    driver.lap(corners, start=0.5, stop=1.003)  # app started mid-lap: half a survey
    assert engine.snapshot().warming_up  # still surveying, nothing learned
    assert store.load("Monza", "Car A", 5).total_runs() == 0
    driver.lap(corners, stop=1.003)  # one complete lap
    assert not engine.snapshot().warming_up
    assert engine.snapshot().boundaries[1:-1] != [0.2, 0.4, 0.6, 0.8]


def test_stored_data_without_sector_lines_keeps_equal_splits(store):
    from brake_trainer.models import TrackData

    legacy = TrackData.empty("Monza", "Car A", 5)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store)
    driver = Driver(engine)
    driver.feed(0.3, 100.0, 0.0)
    assert list(engine.snapshot().boundaries) == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_old_equal_split_reference_does_not_block_the_survey(store):
    corners = [0.20, 0.50, 0.80]
    old = Driver(BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store), car="Car A")
    for _ in range(4):
        old.lap(corners)
    old.engine.flush()
    assert store.load("Monza", "Car A", 5).boundaries is None  # equal splits, like old data

    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store)
    new = Driver(engine, car="Car B")
    new.feed(0.3, 100.0, 0.0)
    assert engine.snapshot().reference_car == "Car A"  # points are borrowed ...
    assert len(engine.snapshot().zones) == 3
    new.lap(corners, stop=1.003)  # ... and the warm-up lap
    lines = list(engine.snapshot().boundaries[1:-1])  # still places new lines
    assert lines != [0.2, 0.4, 0.6, 0.8]
    assert not any(_inside_a_braking_zone(p, corners) for p in lines)
    assert engine.snapshot().reference_car == "Car A"
    assert len(engine.snapshot().zones) == 3  # borrowed zones still cue


def test_snapshot_flags_old_equal_split_data(store):
    from brake_trainer.models import TrackData

    legacy = TrackData.empty("Monza", "Car A", 5)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=1), store)
    Driver(engine).feed(0.3, 100.0, 0.0)
    assert engine.snapshot().equal_lines is True


def _two_excursion_results(store, off_tyres: int = 4):
    """A faster lap with the game invalidating it in sector 2 and tyres off track in sector 4."""
    results = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(
        CORNERS,
        speed_fn=lambda p: 215,
        stop=1.003,
        invalid_from=0.3,  # the lap flag drops in S2
        off_track=(0.65, 0.66),  # a mistake in S4, after the flag is already down
        off_tyres=off_tyres,
    )
    return {r.sector: r for r in results}


def test_a_second_mistake_in_a_later_sector_is_dropped_too(store):
    # S2: the game invalidates the lap; S4: all four tyres off. The live tyre count catches the
    # second one, which the one-shot lap flag cannot.
    by_sector = _two_excursion_results(store)
    assert "invalidated" in by_sector[1].note
    assert by_sector[3].duration is None and "off track" in by_sector[3].note
    for clean in (0, 2, 4):  # the sectors without a mistake are kept
        assert by_sector[clean].accepted


def test_three_tyres_off_is_not_a_track_limit_violation_for_the_game(store):
    # The game only invalidates on all four tyres out; the memory cannot see anything else.
    by_sector = _two_excursion_results(store, off_tyres=3)
    assert by_sector[3].accepted


def test_the_tyre_check_can_be_switched_off(store):
    results = []
    engine = BrakeEngine(
        Settings(n_sectors=5, warmup_laps=0, max_tyres_out=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=1.003, off_track=(0.65, 0.66), off_tyres=4)
    assert {r.sector: r for r in results}[3].accepted  # "Skip sector if tyres off track" is Off


def _warnings_engine(store):
    warnings: list[str] = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_warning=warnings.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    return driver, warnings


def test_a_cut_is_reported_as_not_visible_in_memory(store):
    # The game invalidates the lap, but no four-tyre event is ever reported: a cut.
    driver, warnings = _warnings_engine(store)
    driver.lap(CORNERS, invalid_from=0.5, stop=1.003)
    assert len(warnings) == 1 and "four tyres" in warnings[0]


def test_no_cut_warning_when_four_tyres_were_seen_first(store):
    driver, warnings = _warnings_engine(store)
    driver.lap(
        CORNERS,
        invalid_from=0.5,
        off_track=(0.45, 0.46),  # four tyres off before the lap flag drops
        off_tyres=4,
        stop=1.003,
    )
    assert warnings == []


def test_no_cut_warning_for_a_lap_already_invalid_when_the_app_starts(store):
    # The first sample can land on a lap the app never saw being invalidated: not a cut it saw.
    warnings: list[str] = []
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store, on_warning=warnings.append)
    driver = Driver(engine)
    driver.feed(0.55, 150.0, 0.0, valid=False)
    driver.feed(0.56, 150.0, 0.0, valid=False)
    assert warnings == []
    assert engine.snapshot().pass_flag == "lap invalidated"


def test_snapshot_reports_why_the_sector_will_not_count(store):
    engine = BrakeEngine(Settings(n_sectors=5, warmup_laps=0), store)
    Driver(engine).feed(0.65, 150.0, 0.0, tyres_out=4)
    assert engine.snapshot().pass_flag == "off track"

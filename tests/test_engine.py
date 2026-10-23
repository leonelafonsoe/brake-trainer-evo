from __future__ import annotations

import logging

from brake_trainer.config import Settings
from brake_trainer.engine import N_SECTORS, BrakeEngine, build_zones
from brake_trainer.models import CueKind, SectorRun

from .conftest import DT, LENGTH, Driver

CORNERS = [0.20, 0.50, 0.80]


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
    results = []
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
    from brake_trainer.models import SectorStatus as S

    results: list = []
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
        assert r.delta > 0 and abs(r.delta - (r.duration - r.best)) < 1e-9

    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215)  # beats everything kept
    fast = {r.sector: r for r in results}
    assert all(r.status is S.BEST for r in fast.values())
    for r in fast.values():
        assert r.previous_best is not None and r.delta is not None
        assert r.delta < 0 and abs(r.delta - (r.duration - r.previous_best)) < 1e-9


def test_progress_through_current_sector(make_engine):
    driver = Driver(make_engine())
    driver.feed(0.50, 100.0, 0.0)  # sector 2 spans 1/3..2/3 -> halfway
    snap = driver.engine.snapshot()
    assert snap.sector == 1 and abs(snap.sector_progress - 0.5) < 1e-6


def test_learning_off_keeps_marks_but_still_cues_and_colours(make_engine, store, cues):
    from dataclasses import replace

    from brake_trainer.models import SectorStatus as S

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
    from dataclasses import replace

    results = []
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


def _fast_lap_results(store, **lap_kwargs):
    results = []
    # The lookback is pinned (a 500 m report is 0.1 of this 5000 m lap): these tests exercise the
    # read-back, not the shipped default, which is far smaller.
    settings = Settings(use_game_log=False, warmup_laps=0, cut_give_back_m=500.0)
    engine = BrakeEngine(settings, store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    best_before = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, **lap_kwargs)  # faster everywhere
    best_after = [runs[0].t for runs in store.load("Monza", "Car A", 3).sectors]
    return {r.sector: r for r in results}, best_before, best_after


def test_the_lap_flag_is_read_back_to_the_sector_the_cut_happened_in(store):
    # The game reports a cut only after its give-back window (500 m, 0.1 of this 5000 m lap), so a
    # flag that drops in the middle of S2 is really about a cut in S1, just after its line.
    by_sector, before, after = _fast_lap_results(store, invalid_from=0.52)
    assert by_sector[1].duration is None and "invalidated" in by_sector[1].note
    assert after[1] == before[1]  # the faster-but-invalid sector was not stored
    assert by_sector[0].accepted and after[0] < before[0]  # the sector before is kept
    assert by_sector[2].accepted and after[2] < before[2]  # later sectors were driven cleanly


def test_a_flag_that_drops_after_the_cut_sector_closed_takes_its_run_back(store):
    # The cut is in S2; by the time the game reports it the car is in S3 and S2 has been saved.
    by_sector, before, after = _fast_lap_results(store, invalid_from=0.70)
    assert after[1] == before[1]  # S2's faster run was taken back
    assert by_sector[2].accepted and after[2] < before[2]  # clean S3 kept


def test_sector_with_all_tyres_off_track_is_not_saved(store):
    by_sector, before, after = _fast_lap_results(store, off_track=(0.45, 0.46))
    assert by_sector[1].duration is None and "off track" in by_sector[1].note
    assert after[1] == before[1]
    assert after[0] < before[0] and after[2] < before[2]


def test_validity_checks_can_be_switched_off(store):
    results = []
    settings = Settings(
        use_game_log=False, warmup_laps=0, skip_invalid_sectors=False, max_tyres_out=0
    )
    engine = BrakeEngine(settings, store, on_sector=results.append)
    driver = Driver(engine)
    for _ in range(3):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(CORNERS, invalid_from=0.5, off_track=(0.45, 0.46))
    assert all(r.duration is not None for r in results if r.sector in (0, 1, 2))


def test_first_lap_after_leaving_the_pits_is_not_learned(store):
    results = []
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


def test_stored_data_without_sector_lines_keeps_equal_splits(store):
    from brake_trainer.models import TrackData

    legacy = TrackData.empty("Monza", "Car A", N_SECTORS)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store)
    Driver(engine).feed(0.3, 100.0, 0.0)
    assert list(engine.snapshot().boundaries) == [0.0, 1 / 3, 2 / 3, 1.0]


def test_the_games_splits_set_the_sector_lines(store):
    # The shared memory carries no sector data at all, so the two inner lines come from the game's
    # own splits: the car's position when each was written is the line it crossed.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.0, 100.0, 0.0)  # the first sample opens the session
    assert engine.snapshot().warming_up  # laps are ignored until the lines are known

    for p in (0.10, 0.20, 0.25):
        driver.feed(p, 300.0, 0.0)
    driver.split(0)  # the game's log reports the end of its first sector here
    for p in (0.40, 0.55, 0.60):
        driver.feed(p, 300.0, 0.0)
    driver.split(1)

    snap = engine.snapshot()
    assert list(snap.boundaries) == [0.0, 0.25, 0.60, 1.0]
    assert not snap.warming_up
    assert store.load("Monza", "Car A", N_SECTORS).boundaries == [0.25, 0.60]  # persisted


def test_a_split_is_placed_at_its_own_time_not_the_sample_before_it(store):
    # The game writes the split between two telemetry frames. The line is where the car was at the
    # line's timestamp, not where it was at the previous frame: at racing speed the difference is
    # about a metre, which is enough to see on track.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.20, 300.0, 0.0)
    first = driver.t
    driver.feed(0.22, 300.0, 0.0)
    driver.split(0, at=(first + driver.t) / 2)

    driver.feed(0.58, 300.0, 0.0)
    second = driver.t
    driver.feed(0.60, 300.0, 0.0)
    driver.split(1, at=(second + driver.t) / 2)

    bounds = engine.snapshot().boundaries
    assert abs(bounds[1] - 0.21) < 1e-9  # halfway between 0.20 and 0.22
    assert abs(bounds[2] - 0.59) < 1e-9


def test_a_sector_closes_at_the_line_not_at_the_next_sample(store):
    # Crossing a line between two frames must start the new sector at the crossing, otherwise every
    # sector time is long by up to one frame and the sector bar changes a frame late.
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.32, 200.0, 0.0)  # the pass starts here, at t = DT
    driver.feed(0.36, 200.0, 0.0)  # 1/3 is crossed a third of the way through this frame

    snap = engine.snapshot()
    assert snap.sector == 1
    assert abs(snap.sector_elapsed - (2 / 3) * DT) < 1e-9


def test_a_cut_between_samples_is_attributed_from_the_interpolated_position(store):
    # The line at 1/3 falls between these two frames. Interpolating puts the cut at 0.34 (S2); the
    # previous frame's position, 0.32, would blame S1.
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0, cut_give_back_m=0.0), store)
    driver = Driver(engine)
    driver.feed(0.32, 200.0, 0.0)
    first = driver.t
    driver.feed(0.36, 200.0, 0.0)
    engine.report_infraction("off track", (first + driver.t) / 2)

    snap = engine.snapshot()
    assert snap.sector == 1
    assert snap.pass_flag == "off track"  # S2, where 0.34 is


def test_the_split_audit_measures_the_learned_line_against_the_games(store, caplog):
    # Once the lines are known, every later split is the game saying exactly when it crossed its
    # own line. Comparing that with the app's learned position is the check for a misplaced line.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.10, 300.0, 0.0)
    driver.feed(0.20, 300.0, 0.0)
    driver.split(0)
    driver.feed(0.50, 300.0, 0.0)
    driver.feed(0.60, 300.0, 0.0)
    driver.split(1)
    assert list(engine.snapshot().boundaries[1:-1]) == [0.20, 0.60]

    driver.lap(CORNERS, start=0.0001, stop=1.001)  # one full lap, so the next samples are a new lap
    driver.feed(0.18, 200.0, 0.0)
    first = driver.t
    driver.feed(0.22, 200.0, 0.0)
    # The game's split says its line is at 0.21; the app learned 0.20.
    game_at = first + (0.21 - 0.18) / (0.22 - 0.18) * (driver.t - first)
    with caplog.at_level(logging.DEBUG, logger="brake_trainer.engine"):
        engine.report_split(0, game_at)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "audit index 0" in text and "before the game's" in text


def test_the_sector_that_began_on_the_line_counts_once_the_lines_are_learned(store):
    # The whole lap's splits arrive in one buffered read, often as the car crosses the start/finish
    # line. The S1 that has just begun began on the start/finish line, which both layouts share, and
    # will end on the game's own S1 line, so it is timed correctly: it is not thrown away with the
    # learning lap.
    results = []
    engine = BrakeEngine(Settings(warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    driver.lap(CORNERS, start=0.0001, stop=0.30)
    at0 = driver.t  # the game wrote its first split here
    driver.lap(CORNERS, start=0.31, stop=0.60)
    at1 = driver.t  # ... and its second here
    driver.lap(CORNERS, start=0.61, stop=1.001)  # the lap ends: the next S1 pass begins on the line
    driver.split(0, at0)  # the log is finally read, now
    driver.split(1, at1)

    snap = engine.snapshot()
    assert snap.sector == 0 and not snap.warming_up
    assert list(snap.boundaries[1:-1]) == store.load("Monza", "Car A", N_SECTORS).boundaries

    driver.lap(CORNERS, start=0.001, stop=0.61)  # drive that S1 out
    by_sector = {r.sector: r for r in results}
    assert by_sector[0].duration is not None and by_sector[0].accepted


def test_a_sector_already_running_when_the_lines_are_learned_is_re_timed(store):
    # The same read can instead land with the car mid-sector: that sector began on the equal splits
    # the app had to use until the game's lines were known. The samples still say when the car
    # crossed the game's line, so the pass is moved onto it instead of being thrown away.
    results = []
    engine = BrakeEngine(Settings(warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    driver.lap(CORNERS, start=0.0001, stop=0.30)
    at0 = driver.t
    driver.lap(CORNERS, start=0.30, stop=0.60)
    at1 = driver.t
    driver.lap(CORNERS, start=0.60, stop=0.70)  # the S3 pass is in progress
    driver.split(0, at0)
    driver.split(1, at1)

    driver.lap(CORNERS, start=0.70, stop=1.003)
    re_timed = {r.sector: r for r in results}[2]
    before = driver.t
    driver.lap(CORNERS)  # a whole lap driven on the game's lines, to compare against
    full = driver.t - before
    assert re_timed.duration is not None and re_timed.accepted
    # S3 is the last 40% of the lap (0.60..1.0), not the stand-in last third
    assert abs(re_timed.duration - 0.40 * full) < 0.2


def test_laps_before_the_lines_are_known_are_not_counted(store):
    results = []
    engine = BrakeEngine(Settings(warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    driver.lap(CORNERS)  # a full lap, but the game never said where its lines are
    assert results and all(r.duration is None for r in results)
    assert any("finding the sector lines" in r.note for r in results)
    assert store.load("Monza", "Car A", N_SECTORS).total_runs() == 0


def test_the_lap_the_lines_are_found_on_is_timed_and_places_braking_points(store):
    # The game buffers its log, so the lines can turn up a lap or more late. The sectors that closed
    # before then were dropped, but the samples still know when the car crossed the lines, so the
    # lap is timed after the fact - and the cues follow from those runs.
    engine = BrakeEngine(Settings(warmup_laps=1), store)
    driver = Driver(engine)
    driver.lap([*CORNERS, 0.90])  # lap 0: the out-lap, a warm-up lap
    assert engine.snapshot().zones == ()  # no braking points out of a warm-up lap

    driver.lap(CORNERS, start=0.0001, stop=0.34)  # lap 1: S1 closes on the stand-in line
    driver.split(0)  # the log is read now, and the game's S1 line is about here
    driver.lap(CORNERS, start=0.34, stop=0.70)
    driver.split(1)  # ... and its S2 line here: the lines are learned, mid-sector

    snap = engine.snapshot()
    saved = store.load("Monza", "Car A", N_SECTORS)
    assert saved.sectors[0] and saved.sectors[1]  # the lap is timed from the samples
    assert saved.sectors[2] == []  # ... but not the one still being driven
    assert [round(z, 2) for z in snap.zones] == [0.20, 0.50]  # and their corners are known
    assert saved.early_onsets == []  # the timed runs carry those onsets, no stand-in votes left
    assert not snap.warming_up


def test_the_sectors_the_lines_arrived_too_late_for_are_timed_from_the_samples(store):
    # A whole lap can close before the buffered log brings the lines. Those sectors were measured
    # on the stand-in equal splits and dropped; once the real lines are known the samples can time
    # them, so a fresh track does not lose its first lap to the game's log buffer.
    results = []
    engine = BrakeEngine(Settings(warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    # The app attaches mid-sector: that first pass is partial and is never counted.
    driver.lap(CORNERS, start=0.10, stop=0.30)
    at0 = driver.t
    driver.lap(CORNERS, start=0.30, stop=0.60)
    at1 = driver.t
    driver.lap(CORNERS, start=0.60, stop=1.003)  # lap 0 ends, still on the equal splits
    lap_start = driver.t
    driver.lap(CORNERS, start=0.0001, stop=1.001)  # lap 1, still on the equal splits
    lap_time = driver.t - lap_start

    results.clear()
    driver.lap(CORNERS, start=0.0001, stop=0.05)  # lap 2: the buffered log is finally read
    driver.split(0, at0)  # the game's S1 line ...
    driver.split(1, at1)  # ... and its S2 line, both from lap 0

    timed = [r for r in results if r.duration is not None]
    assert len(timed) == 5 and all(r.accepted for r in timed)
    saved = store.load("Monza", "Car A", N_SECTORS)
    # Lap 0's S2 and S3 (its S1 began mid-sector, so it stays out) plus all of lap 1.
    assert [len(runs) for runs in saved.sectors] == [1, 2, 2]
    lap1 = timed[-3:]
    assert [r.sector for r in lap1] == [0, 1, 2]
    assert abs(sum(r.duration for r in lap1) - lap_time) < 0.3  # a whole lap, line to line


def test_a_sector_the_game_took_out_is_not_timed_when_the_lines_arrive(store):
    # The cut can be reported before the lines are known: recovering the sector's time afterwards
    # would put back a run the game threw away.
    results = []
    engine = BrakeEngine(Settings(warmup_laps=0), store, on_sector=results.append)
    driver = Driver(engine)
    driver.lap(CORNERS, start=0.0001, stop=0.30)
    at0 = driver.t
    driver.lap(CORNERS, start=0.30, stop=0.60)
    at1 = driver.t
    driver.lap(CORNERS, start=0.60, stop=1.003)
    driver.lap(CORNERS, start=0.0001, stop=0.10)  # lap 1 begins, still on the equal splits
    engine.report_infraction("off track", at0 + (at1 - at0) / 2)  # a cut in lap 0's S2

    results.clear()
    driver.split(0, at0)
    driver.split(1, at1)

    saved = store.load("Monza", "Car A", N_SECTORS)
    assert saved.sectors[1] == []  # the cut sector stays out
    assert saved.sectors[2]  # ... its neighbour is recovered


def test_a_partial_pass_keeps_no_braking_points(store):
    # The app can attach to a session already under way: the pass that was running then is partial,
    # so not even its braking points are kept, however long the lines take to arrive.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.lap(CORNERS, start=0.10, stop=0.40)  # attached mid-sector, drove S1's corner
    assert store.load("Monza", "Car A", N_SECTORS).early_onsets == []
    assert engine.snapshot().zones == ()


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


def test_a_stray_split_is_not_taken_for_a_sector_line(store):
    # A split that lands at the start/finish line itself (a teleport or a reset, as the game writes
    # no "Received split" at all on an out-lap) is not the end of the first sector.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.0, 100.0, 0.0)
    driver.feed(0.004, 60.0, 0.0)
    driver.split(0)
    assert store.load("Monza", "Car A", N_SECTORS).boundaries is None
    assert engine.snapshot().warming_up


def test_one_split_alone_does_not_move_the_lines(store):
    # Both lines have to come from the same lap, so a second sector's split is never paired with a
    # first sector's one from another lap.
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine)
    driver.feed(0.0, 100.0, 0.0)
    for p in (0.10, 0.30):
        driver.feed(p, 300.0, 0.0)
    driver.split(0)
    assert store.load("Monza", "Car A", N_SECTORS).boundaries is None


def test_a_log_with_no_splits_falls_back_to_equal_lines_and_still_times_the_first_laps(store):
    messages: list[str] = []
    engine = BrakeEngine(Settings(warmup_laps=0, top_runs=12), store, on_message=messages.append)
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)  # no split is ever reported
    assert not engine.snapshot().warming_up
    saved = store.load("Monza", "Car A", N_SECTORS)
    # Settling for equal splits makes them the real lines, so the three laps driven while waiting
    # are timed after the fact - all but the very first pass, which began mid-sector - and the
    # fourth lap counts live on top (its S3 is still running when the test ends: no wrap).
    assert [len(runs) for runs in saved.sectors] == [3, 4, 3]
    assert sum("no sector splits" in m for m in messages) == 1


def test_a_learned_line_is_shared_with_the_other_cars(store):
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine, car="Car A")
    driver.feed(0.0, 100.0, 0.0)
    for p in (0.20, 0.25):
        driver.feed(p, 300.0, 0.0)
    driver.split(0)
    for p in (0.60, 0.65):
        driver.feed(p, 300.0, 0.0)
    driver.split(1)
    driver.lap(CORNERS, start=0.66, stop=1.003)  # finish the lap the lines were learned on
    driver.lap(CORNERS)  # a clean lap: one stored run, so the other car has a reference
    engine.flush()

    other = Driver(BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store), car="Car B")
    other.feed(0.3, 100.0, 0.0)
    assert list(other.engine.snapshot().boundaries[1:-1]) == [0.25, 0.65]


def test_a_second_car_on_a_learned_track_counts_its_first_lap(store):
    # The lines are the track's, not the car's, so a car driven here for the first time takes the
    # ones another car learned - and, having them, has nothing to wait for: it scores from its
    # first lap, where before it borrowed the lines and then still counted nothing until the
    # game's log repeated them (and, after three laps, said it fell back to equal splits).
    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine, car="Car A")
    driver.feed(0.0, 100.0, 0.0)
    for p in (0.20, 0.25):
        driver.feed(p, 300.0, 0.0)
    driver.split(0)
    for p in (0.60, 0.65):
        driver.feed(p, 300.0, 0.0)
    driver.split(1)
    driver.lap(CORNERS, start=0.66, stop=1.003)  # finish the lap the lines were learned on
    driver.lap(CORNERS)  # a clean lap, so Car A has something to be a reference for
    engine.flush()

    results = []
    messages: list[str] = []
    other = Driver(
        BrakeEngine(
            Settings(warmup_laps=0), store, on_sector=results.append, on_message=messages.append
        ),
        car="Car B",
    )
    other.lap(CORNERS, start=0.999, stop=1.003)  # cross the line: a clean first sector begins
    other.lap(CORNERS, start=0.0001, stop=0.66)

    by_sector = {r.sector: r for r in results}
    assert by_sector[0].accepted and by_sector[1].accepted
    assert other.engine.snapshot().warming_up is False
    assert any("taken from Car A" in m for m in messages)
    assert not any("equal sector" in m for m in messages)
    # The lines are kept with the new car's entry, so it does not depend on Car A's file staying.
    assert store.load("Monza", "Car B", N_SECTORS).boundaries == [0.25, 0.65]


def test_stored_runs_keep_the_lines_they_were_timed_on(store):
    driver = Driver(BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store), car="Car A")
    for _ in range(2):
        driver.lap(CORNERS)
    driver.engine.flush()

    engine = BrakeEngine(Settings(warmup_laps=0), store)
    driver = Driver(engine, car="Car A")
    driver.feed(0.0, 100.0, 0.0)
    assert not engine.snapshot().warming_up  # nothing to wait for: the lines are in use already
    for p in (0.20, 0.25):
        driver.feed(p, 300.0, 0.0)
    driver.split(0)
    for p in (0.60, 0.65):
        driver.feed(p, 300.0, 0.0)
    driver.split(1)
    assert store.load("Monza", "Car A", N_SECTORS).boundaries is None  # the lines are left alone
    assert list(engine.snapshot().boundaries[1:-1]) == [1 / 3, 2 / 3]


def test_snapshot_flags_old_equal_split_data(store):
    from brake_trainer.models import TrackData

    legacy = TrackData.empty("Monza", "Car A", 3)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store)
    Driver(engine).feed(0.3, 100.0, 0.0)
    assert engine.snapshot().equal_lines is True


def _two_excursion_results(store, off_tyres: int = 4, **settings):
    """A faster lap: the game invalidates it in the first sector, tyres off in the second."""
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0, **settings), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(
        CORNERS,
        speed_fn=lambda p: 215,
        stop=1.003,
        invalid_from=0.3,  # the lap flag drops in S1
        off_track=(0.50, 0.51),  # a mistake in S2, after the flag is already down
        off_tyres=off_tyres,
    )
    return {r.sector: r for r in results}


def test_a_second_mistake_in_a_later_sector_is_dropped_too(store):
    # S1: the game invalidates the lap; S2: all four tyres off. The live tyre count catches the
    # second one, which the one-shot lap flag cannot.
    by_sector = _two_excursion_results(store)
    assert "invalidated" in by_sector[0].note
    assert by_sector[1].duration is None and "off track" in by_sector[1].note
    assert by_sector[2].accepted  # the sector without a mistake is kept


def test_a_smaller_excursion_is_dropped_once_the_lap_is_invalid(store):
    # The flag has already dropped, so a two-tyre cut in a later sector is caught by the lower
    # "...once the lap is invalid" limit instead.
    by_sector = _two_excursion_results(store, off_tyres=2)
    assert by_sector[1].duration is None and "off track" in by_sector[1].note
    assert by_sector[2].accepted  # a clean sector after the mistake is still kept


def test_the_same_excursion_is_kept_while_the_lap_is_still_valid(store):
    # No flag has dropped, so only the strict limit (all four tyres) applies.
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_sector=results.append
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=1.003, off_track=(0.50, 0.51), off_tyres=2)
    assert {r.sector: r for r in results}[1].accepted


def test_the_after_invalid_limit_can_be_switched_off(store):
    by_sector = _two_excursion_results(store, off_tyres=3, max_tyres_out_after_invalid=0)
    assert by_sector[1].accepted  # only the strict limit applies after the lap is invalid


def test_the_tyre_check_can_be_switched_off(store):
    results = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0, max_tyres_out=0, max_tyres_out_after_invalid=0),
        store,
        on_sector=results.append,
    )
    driver = Driver(engine)
    for _ in range(4):
        driver.lap(CORNERS)
    results.clear()
    driver.lap(
        CORNERS,
        speed_fn=lambda p: 215,
        stop=1.003,
        invalid_from=0.3,  # the lap is invalid, but both tyre checks are Off
        off_track=(0.50, 0.51),
        off_tyres=4,
    )
    assert {r.sector: r for r in results}[1].accepted


def test_a_second_off_is_caught_by_the_games_race_cut_signal(store):
    # The one-shot lap flag drops in S1. The race-cut pair the game fills in for a second
    # off-track in S2 lets that sector be dropped too, with no tyres-out event involved.
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
    Driver(engine).feed(0.65, 150.0, 0.0, tyres_out=4)
    assert engine.snapshot().pass_flag == "off track"


def test_verbose_logging_traces_the_track_limit_signals(store, caplog):
    import logging

    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    driver = Driver(engine)
    with caplog.at_level(logging.DEBUG, logger="brake_trainer.engine"):
        driver.feed(0.10, 150.0, 0.0)
        driver.feed(0.11, 150.0, 0.0, tyres_out=4)
        driver.feed(0.12, 150.0, 0.0, tyres_out=0)
        driver.feed(0.13, 150.0, 0.0, cut_gained_ms=250, cut_deadline_m=120)
        driver.feed(0.14, 150.0, 0.0)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "tyres_out 0 -> 4" in text
    assert "tyres_out 4 -> 0" in text
    assert "race_cut up" in text and "gained=250 ms" in text
    assert "race_cut clear" in text
    assert "lap_valid None -> True" in text

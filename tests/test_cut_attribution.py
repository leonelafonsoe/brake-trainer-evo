from __future__ import annotations

import logging

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import _HISTORY_S, N_SECTORS, BrakeEngine, _LapRun
from brake_trainer.models import SectorRun, SectorStatus, TrackData
from brake_trainer.timeline import crossing_between

from .conftest import DT, LENGTH, Driver
from .engine_helpers import CORNERS, MONZA_LENGTH_M, MONZA_LINES


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


# The field logs from the old build, which trusted the report position, put cuts at 67.1% and
# 68.3% (Ascari) and the app was told about a cut at 71.6%/72.6% (curve 10, the last Ascari
# before Parabolica). All are past the 65.67% S2/S3 line, so all are S3. Reading the report
# back by a fixed 500 m moved them into S2 - the wrong sector on the bar.
# 36.3% of the app's lap is Lesmo 1, in S2. A fixed 500 m read-back put it at 27.7%, in S1, and
# took back the clean S1 run instead of the cut S2 one.
MONZA_CUTS = [
    pytest.param(0.671, 2, id="ascari-67.1"),
    pytest.param(0.683, 2, id="ascari-68.3"),
    pytest.param(0.716, 2, id="ascari-71.6"),
    pytest.param(0.726, 2, id="ascari-72.6"),
    pytest.param(0.363, 1, id="lesmo-36.3"),
    # 2026-10-25 field session, app 0.5.0 / game 0.9.1: deliberate cuts at Lesmo, Ascari and
    # Parabolica. This pins the S2/S3 boundary and the start/finish-seam case as well.
    pytest.param(0.506, 1, id="field-lesmo-50.6"),
    pytest.param(0.514, 1, id="field-lesmo-51.4"),
    pytest.param(0.957, 2, id="field-parabolica-95.7"),
]


@pytest.mark.parametrize(("reported_at", "sector"), MONZA_CUTS)
def test_a_monza_cut_drops_the_sector_the_game_reported_it_in(store, reported_at, sector):
    engine, driver, _, messages = _engine(store, boundaries=MONZA_LINES, length=MONZA_LENGTH_M)
    driver.lap(CORNERS, speed_fn=lambda p: 215, stop=reported_at)
    engine.report_infraction("the game reported a cut", driver.t)

    lap = engine._lap_no
    assert (lap, sector) in engine._invalid_sectors  # where the game reported the cut
    assert (lap, sector - 1) not in engine._invalid_sectors  # not a fixed distance behind it
    assert any(
        f"S{sector + 1}" in m and ("won't count" in m or "taken back" in m) for m in messages
    )
    assert not any(f"S{sector}" in m for m in messages if "reported a cut" in m)


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


# A buffered log can hold a minute of lines, so a batch can carry cuts from far apart. Each is
# attributed from its own time: both sectors go, and the clean one between them stays.
# Two reports can also arrive in one read, seconds apart, one in S1 and another in S2: the second
# must not be folded into the first, even though the app saw them close together in time.
TWO_CUT_BATCHES = [
    pytest.param((0.30, 0.90), (0, 2), 1, id="one-batch-s1-and-s3"),
    pytest.param((0.30, 0.60), (0, 1), None, id="seconds-apart-s1-and-s2"),
]


@pytest.mark.parametrize(("positions", "pending", "clean"), TWO_CUT_BATCHES)
def test_two_cuts_read_in_one_batch_each_drop_their_own_sector(store, positions, pending, clean):
    engine, driver, _, messages = _engine(store)
    times = []
    for position in positions:
        driver.feed(position, 215.0, 0.0)
        times.append(driver.t)
    for at in times:  # read only now, together
        engine.report_infraction("the game reported a cut", at)

    assert sum("the game reported a cut" in m for m in messages) == 2
    status = engine.snapshot().sector_status
    for sector in pending:
        assert status[sector] is SectorStatus.PENDING
    if clean is not None:  # the sector between the two, where the batch has one
        assert status[clean] is not SectorStatus.PENDING
    assert engine.snapshot().pass_flag == "off track"  # the sector being driven is one of them


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

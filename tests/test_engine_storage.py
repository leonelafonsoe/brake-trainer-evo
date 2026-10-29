from __future__ import annotations

import json

from brake_trainer.config import Settings
from brake_trainer.engine import N_SECTORS, BrakeEngine
from brake_trainer.models import DATA_VERSION, SectorResult, SectorRun, TrackData
from brake_trainer.storage import DeleteSector, StoreResult

from .conftest import Driver
from .engine_helpers import CORNERS


def test_a_failed_save_is_shown_until_a_save_succeeds(store, monkeypatch):
    messages: list[str] = []
    warnings: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0),
        store,
        on_message=messages.append,
        on_warning=warnings.append,
    )
    driver = Driver(engine)
    failing = {"on": True}
    real_save = store.save

    def save(data):
        if failing["on"]:
            return StoreResult(ok=False, detail="No space left on device")
        return real_save(data)

    monkeypatch.setattr(store, "save", save)
    for _ in range(4):
        driver.lap(CORNERS)

    snap = engine.snapshot()
    assert snap.storage_warning == "Could not save learned data · see the log"
    assert warnings == ["Could not save learned data: No space left on device"]
    assert not store.load("Monza", "Car A", N_SECTORS).total_runs()  # nothing was written

    failing["on"] = False
    engine.flush()

    assert engine.snapshot().storage_warning == ""
    assert messages.count("Learned data can be saved again") == 1
    assert store.load("Monza", "Car A", N_SECTORS).total_runs() > 0


def test_a_failed_data_edit_is_reported_and_keeps_the_warning_up(store, monkeypatch):
    warnings: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0), store, on_warning=warnings.append
    )
    driver = Driver(engine)
    driver.feed(0.1, 100.0, 0.0)
    monkeypatch.setattr(
        store, "apply", lambda edit: StoreResult(ok=False, detail="Permission denied")
    )

    engine.queue_edit(DeleteSector("Monza", "Car A", 0))

    assert engine.apply_pending() is False  # a failed edit changed nothing
    assert engine.snapshot().storage_warning
    assert warnings == ["Could not save learned data: Permission denied"]


def test_a_newer_data_file_is_quarantined_not_overwritten(store):
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = TrackData.empty("Monza", "Car A", N_SECTORS).to_dict()
    raw["version"] = DATA_VERSION + 1
    original = json.dumps(raw)
    path.write_text(original, encoding="utf-8")

    warnings: list[str] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0),
        store,
        on_warning=warnings.append,
    )
    driver = Driver(engine)
    driver.feed(0.1, 100.0, 0.0)
    engine.flush()  # the shutdown save must not overwrite the newer file

    quarantined = list(store.quarantine_directory.glob("Monza__Car_A.newer-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == original
    assert path.exists()  # a fresh entry starts in its place
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == DATA_VERSION
    assert engine.snapshot().storage_warning
    assert warnings


def test_stored_data_without_sector_lines_keeps_equal_splits(store):
    legacy = TrackData.empty("Monza", "Car A", N_SECTORS)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store)
    Driver(engine).feed(0.3, 100.0, 0.0)
    assert list(engine.snapshot().boundaries) == [0.0, 1 / 3, 2 / 3, 1.0]


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
    legacy = TrackData.empty("Monza", "Car A", 3)
    legacy.sectors[0].append(SectorRun(18.0, [0.05]))
    store.save(legacy)
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=1), store)
    Driver(engine).feed(0.3, 100.0, 0.0)
    assert engine.snapshot().equal_lines is True


def test_each_accepted_sector_saves_and_rebuilds_zones_once(store, monkeypatch):
    # On Windows with real-time antivirus, a second JSON write per sector can stall the telemetry
    # loop. Keep the common path at one save and one rebuild, with a single rebuild when the session
    # starts.
    results: list[SectorResult] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0),
        store,
        on_sector=results.append,
    )
    driver = Driver(engine)
    saves: list[int] = []
    rebuilds: list[int] = []
    real_save, real_rebuild = store.save, engine._rebuild_zones

    def save(data):
        saves.append(1)
        return real_save(data)

    def rebuild():
        rebuilds.append(1)
        real_rebuild()

    monkeypatch.setattr(store, "save", save)
    monkeypatch.setattr(engine, "_rebuild_zones", rebuild)

    for _ in range(5):
        driver.lap(CORNERS)

    accepted = sum(1 for result in results if result.duration is not None and result.accepted)
    assert accepted > 0
    assert len(saves) == accepted
    assert len(rebuilds) == accepted + 1  # the session's first zone build

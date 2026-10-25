"""The worker owns the engine: UI changes are queued, never applied from the UI thread."""

from __future__ import annotations

from dataclasses import replace

from brake_trainer.audio import AudioPlayer
from brake_trainer.config import Settings, SettingsHolder
from brake_trainer.engine import BrakeEngine
from brake_trainer.ui.worker import EngineWorker

from .conftest import Driver

CORNERS = [0.20, 0.50, 0.80]


def _worker(store) -> EngineWorker:
    holder = SettingsHolder(Settings(use_game_log=False, warmup_laps=0))
    audio = AudioPlayer(lambda: holder.value, backend=lambda _wav: None)
    return EngineWorker(holder, store, audio)


def test_a_settings_change_is_only_queued_until_the_worker_runs_it(qapp, store):
    worker = _worker(store)
    engine: BrakeEngine = worker._engine
    applied: list[Settings] = []
    original = engine.apply_settings

    def counting_apply(settings: Settings) -> None:
        applied.append(settings)
        original(settings)

    engine.apply_settings = counting_apply
    new = replace(engine.settings, learning_enabled=False)

    worker.update_settings(new)
    assert engine.settings is not new  # the UI did not mutate the engine
    assert applied == []

    driver = Driver(engine)
    driver.feed(0.0001, 100.0, 0.0)
    assert engine.settings is new
    assert applied == [new]

    driver.feed(0.1, 100.0, 0.0)
    assert applied == [new]  # applied exactly once, not on every sample


def test_a_queued_settings_change_rebuilds_zones_once(qapp, store):
    worker = _worker(store)
    driver = Driver(worker._engine)
    for _ in range(4):
        driver.lap(CORNERS)
    assert driver.engine.snapshot().zones

    rebuilt: list[int] = []
    original = worker._engine._rebuild_zones

    def counting_rebuild() -> None:
        rebuilt.append(1)
        original()

    worker._engine._rebuild_zones = counting_rebuild
    worker.update_settings(replace(driver.engine.settings, min_peak=1.0))

    driver.feed(0.0001, 100.0, 0.0)
    assert rebuilt == [1]
    driver.feed(0.1, 100.0, 0.0)
    assert rebuilt == [1]  # the reload flag is consumed by the first sample

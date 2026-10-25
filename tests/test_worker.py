"""The worker owns the engine: UI changes are queued, never applied from the UI thread."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

from brake_trainer.audio import AudioPlayer
from brake_trainer.config import Settings, SettingsHolder
from brake_trainer.engine import BrakeEngine
from brake_trainer.telemetry import ExitReason
from brake_trainer.ui import worker as worker_module
from brake_trainer.ui.worker import EngineWorker

from .conftest import Driver

CORNERS = [0.20, 0.50, 0.80]


def _worker(store) -> EngineWorker:
    holder = SettingsHolder(Settings(use_game_log=False, warmup_laps=0))
    audio = AudioPlayer(lambda: holder.value, backend=lambda _wav: None)
    return EngineWorker(holder, store, audio)


def _count_flushes(worker: EngineWorker) -> list[int]:
    flushed: list[int] = []
    original = worker._engine.flush

    def counting_flush() -> None:
        flushed.append(1)
        original()

    worker._engine.flush = counting_flush
    return flushed


def _install_reader(monkeypatch, *, delay: float = 0.0) -> tuple[list, threading.Event]:
    """Replace the real telemetry reader; its run() waits for the stop event after ``delay``."""
    readers: list = []
    created = threading.Event()

    class FakeReader:
        def __init__(self, *args, **kwargs) -> None:
            self.started = threading.Event()
            readers.append(self)
            created.set()

        async def run(self, stop) -> ExitReason:
            self.started.set()
            if delay:
                await asyncio.sleep(delay)  # a slow start-up probe
            while not stop.is_set():
                await asyncio.sleep(0.01)
            return ExitReason.STOPPED

    monkeypatch.setattr(worker_module, "TelemetryReader", FakeReader)
    return readers, created


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


def test_stop_requested_before_the_thread_starts_is_not_lost(qapp, store, monkeypatch):
    readers, _ = _install_reader(monkeypatch)
    worker = _worker(store)
    flushed = _count_flushes(worker)

    worker.request_stop()  # quit while the window is still being built
    worker.start()

    assert worker.wait(5000)
    assert readers[0].started.is_set()
    assert flushed == [1]


def test_stop_during_a_slow_probe_finishes_and_flushes_once(qapp, store, monkeypatch):
    readers, created = _install_reader(monkeypatch, delay=0.3)
    worker = _worker(store)
    flushed = _count_flushes(worker)

    worker.start()
    try:
        assert created.wait(2.0)
        worker.request_stop()  # the reader is still inside its start-up probe
        assert worker.wait(5000)
    finally:
        worker.request_stop()
        worker.wait(5000)
    assert flushed == [1]


def test_a_crashed_loop_still_flushes_once(qapp, store, monkeypatch):
    class CrashingReader:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self, stop) -> ExitReason:
            raise RuntimeError("the telemetry probe failed")

    monkeypatch.setattr(worker_module, "TelemetryReader", CrashingReader)
    worker = _worker(store)
    flushed = _count_flushes(worker)

    worker.start()
    assert worker.wait(5000)
    assert flushed == [1]

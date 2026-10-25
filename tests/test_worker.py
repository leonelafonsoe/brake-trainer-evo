"""The worker owns the engine: UI changes are queued, never applied from the UI thread."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace

from brake_trainer.audio import AudioPlayer
from brake_trainer.config import Settings, SettingsHolder
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import Sample, SectorRun, TrackData
from brake_trainer.storage import DeleteRun, DeleteSector
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
    states: list = []
    worker.state.connect(states.append)

    worker.start()
    assert worker.wait(5000)
    assert flushed == [1]
    # The HUD must not keep saying "waiting for the game" after the worker has died.
    _pump(qapp, lambda: bool(states), "a visible crash state")
    assert states[-1].error == "Telemetry worker stopped · see the log"


def test_a_telemetry_error_reaches_the_view_state_and_clears_on_recovery(qapp, store):
    worker = _worker(store)
    states: list = []
    worker.state.connect(states.append)

    worker._on_telemetry_error("capture could not start")
    assert states[-1].error.startswith("Telemetry failed: capture could not start")
    assert "brake_trainer.log" in states[-1].error

    worker._on_telemetry_error("")
    assert states[-1].error == ""


def _pump(qapp, condition, what: str, timeout: float = 2.0) -> None:
    """Process queued Qt signals until ``condition`` is true (or fail with a useful message)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def test_the_worker_streams_samples_and_reports_the_game_closing(qapp, store, monkeypatch):
    class SamplingReader:
        def __init__(self, get_settings, on_sample, *args, **kwargs) -> None:
            self._on_sample = on_sample

        async def run(self, stop) -> ExitReason:
            self._on_sample(
                Sample(
                    track="Monza",
                    car="Car A",
                    length_m=5000.0,
                    pos=0.1,
                    brake=0.0,
                    speed_kmh=123.0,
                    in_pit=False,
                    t=1.0,
                )
            )
            return ExitReason.GAME_CLOSED

    monkeypatch.setattr(worker_module, "TelemetryReader", SamplingReader)
    worker = _worker(store)
    states: list = []
    closed: list = []
    worker.state.connect(states.append)
    worker.game_closed.connect(lambda: closed.append(1))

    worker.start()
    assert worker.wait(5000)
    _pump(qapp, lambda: bool(states) and bool(closed), "a live state and game_closed")

    live = [state for state in states if state.live]
    assert live and live[-1].snapshot.track == "Monza"
    assert live[-1].snapshot.speed_kmh == 123.0
    assert closed == [1]


def test_a_sample_older_than_the_timeout_is_not_shown_as_live(qapp, store):
    worker = _worker(store)
    states: list = []
    worker.state.connect(states.append)

    worker._on_sample(
        Sample(
            track="Monza",
            car="Car A",
            length_m=5000.0,
            pos=0.1,
            brake=0.0,
            speed_kmh=100.0,
            in_pit=False,
            t=1.0,
        )
    )
    assert states[-1].live

    worker._last_sample -= worker_module._LIVE_TIMEOUT_S + 0.1
    worker._emit()
    assert not states[-1].live  # the reader has gone quiet; the HUD must not freeze on old data


def test_a_data_edit_requested_by_the_ui_is_applied_on_the_next_pending_pass(qapp, store):
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05]), SectorRun(19.0, [])]
    assert store.save(data)
    worker = _worker(store)
    changed: list = []
    worker.data_changed.connect(lambda: changed.append(1))

    worker.request_edit(DeleteRun("Monza", "Car A", 0, 18.0, (0.05,)))
    # Queued, not applied from the UI thread: the file is untouched until the worker's pass.
    assert len(store.load("Monza", "Car A", 3).sectors[0]) == 2

    assert worker._engine.apply_pending() is True
    assert [run.t for run in store.load("Monza", "Car A", 3).sectors[0]] == [19.0]
    assert changed == [1]


def test_a_game_log_cut_reaches_the_engine_and_publishes_state(qapp, store):
    worker = _worker(store)
    states: list = []
    worker.state.connect(states.append)
    driver = Driver(worker._engine)
    driver.feed(0.10, 200.0, 0.0)
    driver.feed(0.16, 200.0, 0.0)

    worker._on_cut("the game reported a cut", driver.t)

    assert worker._engine.snapshot().pass_flag == "off track"
    _pump(qapp, lambda: bool(states), "a state after the cut")
    assert states[-1].snapshot.pass_flag == "off track"


def test_a_game_log_split_teaches_the_engine(qapp, store):
    holder = SettingsHolder(Settings(use_game_log=True, warmup_laps=0))
    audio = AudioPlayer(lambda: holder.value, backend=lambda _wav: None)
    worker = EngineWorker(holder, store, audio)
    states: list = []
    worker.state.connect(states.append)
    driver = Driver(worker._engine)
    for pos in (0.10, 0.20, 0.25):
        driver.feed(pos, 300.0, 0.0)
    worker._on_split(0, driver.t)
    for pos in (0.60, 0.65):
        driver.feed(pos, 300.0, 0.0)
    worker._on_split(1, driver.t)

    assert list(worker._engine.snapshot().boundaries[1:-1]) == [0.25, 0.65]
    _pump(qapp, lambda: bool(states), "a state after the splits")
    assert not states[-1].snapshot.warming_up


def test_the_idle_tick_applies_edits_and_publishes_state(qapp, store):
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05])]
    assert store.save(data)
    worker = _worker(store)
    states: list = []
    worker.state.connect(states.append)
    worker.request_edit(DeleteSector("Monza", "Car A", 0))

    worker._tick()

    assert store.load("Monza", "Car A", 3).sectors[0] == []
    _pump(qapp, lambda: bool(states), "a state from the idle tick")


def test_a_sector_delete_requested_by_the_ui_passes_through_the_worker(qapp, store):
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05])]
    data.sectors[1] = [SectorRun(20.0, [0.4])]
    assert store.save(data)
    worker = _worker(store)

    worker.request_edit(DeleteSector("Monza", "Car A", 0))

    assert worker._engine.apply_pending() is True
    reloaded = store.load("Monza", "Car A", 3)
    assert reloaded.sectors[0] == []
    assert [run.t for run in reloaded.sectors[1]] == [20.0]

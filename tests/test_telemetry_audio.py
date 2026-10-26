from __future__ import annotations

import asyncio
import io
import logging
import math
import struct
import threading
import time
import wave
from types import SimpleNamespace

import pytest

from brake_trainer import audio as audio_module
from brake_trainer.audio import AudioPlayer, make_tone
from brake_trainer.config import Settings
from brake_trainer.models import CueKind
from brake_trainer.telemetry import (
    TRACK_LIMITS_NOTE,
    ExitReason,
    GameProbe,
    GameStatus,
    TelemetryReader,
    _GameWatch,
    find_game_process,
    sample_from_frame,
)


async def _wait(condition, timeout: float = 3.0) -> bool:
    """Poll a condition instead of sleeping for a guessed duration."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


def frame(**over):
    base = SimpleNamespace(
        timestamp="2026-10-08T22:20:38.550451+00:00",
        graphics={
            "normalized_car_position": 0.42,
            "car_model": "Ferrari 296 GTB",
            "is_in_pit_lane": False,
            "is_valid_lap": False,
        },
        physics={"brake": 0.7, "speed_kmh": 120.0},
        static={"track": "Monza", "track_length_m": 5793.0},
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_the_startup_track_limits_note_only_names_current_signals():
    # The live tyre-count path was removed; the note must not send users looking for a setting that
    # no longer exists. The log's older tyre-count parser is a different, historical signal.
    assert "tyres" not in TRACK_LIMITS_NOTE.lower()
    assert "log" in TRACK_LIMITS_NOTE
    assert "race-cut" in TRACK_LIMITS_NOTE
    assert "is_valid_lap" in TRACK_LIMITS_NOTE


def test_sample_from_frame():
    s = sample_from_frame(frame())
    assert s is not None
    assert (s.track, s.car, s.pos) == ("Monza", "Ferrari 296 GTB", 0.42)
    assert (s.brake, s.length_m) == (0.7, 5793.0)
    assert s.lap_valid is False
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)  # no raw graphics


def _raw_graphics(gained: int, deadline: int, delta: float) -> str:
    """The raw graphics region as the SDK hands it over, with the race-cut fields written."""
    raw = bytearray(4096)
    struct.pack_into("<i", raw, 2464, gained)  # race_cut_gained_time_ms
    struct.pack_into("<i", raw, 2468, deadline)  # distance_to_deadline
    struct.pack_into("<f", raw, 2472, delta)  # race_cut_current_delta
    return bytes(raw).hex()


def test_sample_reads_the_race_cut_fields_from_the_raw_graphics_block():
    s = sample_from_frame(frame(graphics_raw=_raw_graphics(320, 150, -0.42)))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m) == (320, 150)
    assert abs(s.cut_delta_s + 0.42) < 1e-6


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("00", "too short"),
        (bytes(4096), "the raw block, cut short before the race-cut fields"),
        ("zz" * 2500, "long enough, but not hex text"),
        (bytes(6000), "the raw block itself, not hex text"),
    ],
)
def test_sample_ignores_a_short_or_corrupt_raw_graphics_block(raw, why):
    s = sample_from_frame(frame(graphics_raw=raw))
    assert s is not None, why
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)


@pytest.mark.parametrize(
    ("gained", "deadline", "delta"),
    [
        (0, 150, -0.42),  # a give-back distance with no time gained is not a cut
        (-320, 150, -0.42),
        (60_001, 150, -0.42),
        (320, -1, -0.42),
        (320, 5_001, -0.42),
        (320, 150, math.inf),
        (320, 150, math.nan),
    ],
)
def test_sample_treats_an_out_of_range_race_cut_block_as_no_cut(gained, deadline, delta):
    s = sample_from_frame(frame(graphics_raw=_raw_graphics(gained, deadline, delta)))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)


def test_sample_rejects_a_shifted_but_plausible_looking_race_cut_block():
    # The block moved four bytes earlier in a game update: the read now sees the deadline as the
    # gain (150 ms looks plausible) and the delta's float bits as the deadline, which does not.
    raw = bytearray(4096)
    struct.pack_into("<i", raw, 2460, 320)
    struct.pack_into("<i", raw, 2464, 150)
    struct.pack_into("<f", raw, 2468, -0.42)
    s = sample_from_frame(frame(graphics_raw=bytes(raw).hex()))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)


@pytest.mark.parametrize(
    "bad",
    [
        frame(static={}),
        frame(graphics={}),
        frame(graphics={"error": "x"}),
        frame(physics={"error": "x"}),
        frame(graphics=None),
    ],
)
def test_sample_rejected_outside_a_session(bad):
    assert sample_from_frame(bad) is None


def test_find_game_process_parses_tasklist():
    out = SimpleNamespace(
        stdout='"System","4","Services","0","100 K"\n'
        '"AssettoCorsaEVO.exe","99","Console","1","9 K"\n'
    )
    probe = find_game_process("assettocorsaevo", run=lambda *a, **k: out)
    assert probe == GameProbe(GameStatus.RUNNING, "AssettoCorsaEVO.exe", 99)
    assert find_game_process("nothing", run=lambda *a, **k: out).status is GameStatus.ABSENT

    def boom(*a, **k):
        raise OSError

    assert find_game_process("x", run=boom).status is GameStatus.UNKNOWN


class FakeCapture:
    created: list[FakeCapture] = []

    def __init__(self, hz):
        self.index = len(FakeCapture.created)
        FakeCapture.created.append(self)
        self.running, self.polls = False, 0

    async def start_capture(self):
        self.running = True

    async def stop_capture(self):
        self.running = False

    def is_capturing(self):
        self.polls += 1
        if self.index == 0 and self.polls > 3:
            self.running = False  # SDK stops by itself, e.g. idle timeout
        return self.running

    def get_stop_reason(self):
        return "idle_timeout"

    def get_frames(self):
        return [frame()]

    def clear(self):
        pass


class FakeWatcher:
    """Stands in for a process handle: reports exit after a number of polls."""

    def __init__(self, exits_after: int) -> None:
        self.polls, self.exits_after, self.closed = 0, exits_after, False

    def exited(self) -> bool:
        self.polls += 1
        return self.polls > self.exits_after

    def close(self) -> None:
        self.closed = True


def _fast(monkeypatch):
    import brake_trainer.telemetry as tel

    monkeypatch.setattr(tel, "_PROBE_WAITING_S", 0.0)
    monkeypatch.setattr(tel, "_PROBE_FALLBACK_S", 0.0)
    monkeypatch.setattr(tel, "_RESTART_DELAY_S", 0.0)
    FakeCapture.created.clear()


async def test_reader_restarts_and_exits_instantly_with_a_process_handle(monkeypatch):
    _fast(monkeypatch)
    probe_calls, samples, restarts, states = [], [], [], []
    watcher = FakeWatcher(exits_after=8)

    def probe(_):
        probe_calls.append(1)
        return GameProbe(GameStatus.RUNNING, "AssettoCorsaEVO.exe", 4242)

    reader = TelemetryReader(
        lambda: Settings(),
        samples.append,
        on_game_state=states.append,
        capture_factory=FakeCapture,
        game_probe=probe,
        process_watcher=lambda pid: watcher if pid == 4242 else None,
        on_restart=lambda: restarts.append(1),
        poll_s=0.001,
    )
    reason = await asyncio.wait_for(reader.run(asyncio.Event()), 5)
    assert reason is ExitReason.GAME_CLOSED
    assert len(probe_calls) == 1  # no process listing once we hold a handle
    assert watcher.closed and states == [True, False]
    assert len(FakeCapture.created) == 2 and restarts and samples


class _FakeWatcher:
    def __init__(self) -> None:
        self.exited_now = False
        self.closed = False

    def exited(self) -> bool:
        return self.exited_now

    def close(self) -> None:
        self.closed = True


async def test_game_watch_opens_a_handle_and_reports_the_exit():
    watchers: list[_FakeWatcher] = []

    def open_watcher(_pid: int) -> _FakeWatcher:
        watcher = _FakeWatcher()
        watchers.append(watcher)
        return watcher

    watch = _GameWatch(
        lambda _: GameProbe(GameStatus.RUNNING, "ACE.exe", 7),
        open_watcher,
        clock=iter([10.0, 20.0]).__next__,
    )

    first = await watch.poll("ace")
    assert first.detected == "ACE.exe" and not first.closed

    watchers[0].exited_now = True
    assert (await watch.poll("ace")).closed

    watch.close()
    assert watchers[0].closed


async def test_game_watch_needs_two_misses_before_closing():
    probes = iter(
        [
            GameProbe(GameStatus.RUNNING, "ACE.exe", 0),
            GameProbe(GameStatus.ABSENT),
            GameProbe(GameStatus.ABSENT),
        ]
    )
    watch = _GameWatch(
        lambda _: next(probes),
        lambda _pid: None,  # no handle: fall back to polling
        clock=iter([10.0, 20.0, 30.0]).__next__,
    )

    assert (await watch.poll("ace")).detected == "ACE.exe"
    assert not (await watch.poll("ace")).closed
    assert (await watch.poll("ace")).closed


async def test_game_watch_waits_before_probing_again():
    calls: list[str] = []
    probes = [GameProbe(GameStatus.UNKNOWN)] * 3
    watch = _GameWatch(
        lambda name: calls.append(name) or probes.pop(0),
        lambda _pid: None,
        clock=iter([10.0, 11.0, 20.0]).__next__,
    )

    await watch.poll("ace")
    await watch.poll("ace")  # inside the 3 s waiting cadence: no probe
    await watch.poll("ace")

    assert len(calls) == 2


async def test_reader_falls_back_to_polling_without_a_handle(monkeypatch):
    _fast(monkeypatch)
    probes = iter(
        [GameProbe(GameStatus.RUNNING, "AssettoCorsaEVO.exe", 7)] * 3
        + [GameProbe(GameStatus.ABSENT)] * 5
    )
    states = []
    reader = TelemetryReader(
        lambda: Settings(),
        lambda s: None,
        on_game_state=states.append,
        capture_factory=FakeCapture,
        game_probe=lambda _: next(probes),
        process_watcher=lambda pid: None,  # e.g. access denied
        poll_s=0.001,
    )
    reason = await asyncio.wait_for(reader.run(asyncio.Event()), 5)
    assert reason is ExitReason.GAME_CLOSED and states == [True, False]


async def test_reader_unknown_probe_never_closes(monkeypatch):
    _fast(monkeypatch)
    probes = iter([GameProbe(GameStatus.RUNNING, "x", 0)] + [GameProbe(GameStatus.UNKNOWN)] * 1000)
    seen = {"n": 0}

    def probe(_):
        seen["n"] += 1
        return next(probes)

    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        lambda s: None,
        capture_factory=FakeCapture,
        game_probe=probe,
        process_watcher=lambda pid: None,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    assert await _wait(lambda: seen["n"] >= 3)
    assert not task.done()
    stop.set()
    assert await task is ExitReason.STOPPED


def test_an_empty_process_name_never_matches_the_task_list():
    from brake_trainer.telemetry import GameStatus, find_game_process

    class Result:
        stdout = '"System","4","Services","0","100 K"\n"explorer.exe","9","Console","1","1 K"\n'

    assert find_game_process("", run=lambda *args, **kwargs: Result()).status is GameStatus.UNKNOWN
    assert (
        find_game_process("   ", run=lambda *args, **kwargs: Result()).status is GameStatus.UNKNOWN
    )


def test_open_process_watcher_is_a_noop_off_windows():
    import sys

    from brake_trainer.telemetry import open_process_watcher

    if sys.platform != "win32":
        assert open_process_watcher(1234) is None
    assert open_process_watcher(0) is None


def test_make_tone_is_valid_wav_and_volume_scales():
    quiet, loud = make_tone(1000, 50, 0.1), make_tone(1000, 50, 1.0)
    with wave.open(io.BytesIO(loud)) as w:
        assert w.getnframes() == int(22050 * 0.05)

    def peak(wav: bytes) -> int:
        samples = struct.unpack(f"<{(len(wav) - 44) // 2}h", wav[44:])
        return max(abs(x) for x in samples)

    assert peak(quiet) < peak(loud) / 5


def test_audio_player_respects_a_zero_volume():
    played = []
    done = threading.Event()

    def backend(wav: bytes) -> None:
        played.append(wav)
        done.set()

    holder = {"st": Settings(volume=0.0)}
    player = AudioPlayer(lambda: holder["st"], backend=backend)
    player.play(CueKind.WARN)
    assert played == []
    player.play(CueKind.HERE, force=True)
    assert done.wait(1)  # the cue runs on its own thread; wait for it, do not sleep
    assert len(played) == 1


def test_a_failing_audio_backend_never_reaches_the_driver(monkeypatch, caplog):
    # A removed headset or a locked audio device must not take the overlay down mid-lap.
    def broken(wav: bytes) -> None:
        raise OSError("no audio device")

    player = AudioPlayer(lambda: Settings(), backend=broken)

    class InlineThread:
        def __init__(self, target, args=(), daemon=None) -> None:
            self._target, self._args = target, args

        def start(self) -> None:
            self._target(*self._args)

    monkeypatch.setattr(audio_module.threading, "Thread", InlineThread)
    with caplog.at_level(logging.ERROR, logger="brake_trainer.audio"):
        player.play(CueKind.WARN, force=True)  # the failure is logged, not raised
    assert "Could not play cue" in caplog.text


async def test_reader_reports_a_capture_start_failure_and_recovers(monkeypatch):
    _fast(monkeypatch)
    attempts, errors = [], []

    class FlakyCapture(FakeCapture):
        async def start_capture(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("shared memory unavailable")
            await super().start_capture()

    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        lambda s: None,
        capture_factory=FlakyCapture,
        game_probe=lambda _: GameProbe(GameStatus.RUNNING, "x", 0),
        process_watcher=lambda pid: None,
        on_error=errors.append,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    assert await _wait(lambda: "" in errors)
    stop.set()

    assert await task is ExitReason.STOPPED
    assert errors[0] == "capture could not start"
    assert "" in errors  # the next successful start cleared it
    assert len(attempts) >= 2  # it retried instead of dying


async def test_reader_reports_a_read_failure_and_recovers(monkeypatch):
    _fast(monkeypatch)
    errors = []

    class FlakyFrames(FakeCapture):
        def __init__(self, hz):
            super().__init__(hz)
            self.failed = False

        def get_frames(self):
            if not self.failed:
                self.failed = True
                raise OSError("shared memory went away")
            return super().get_frames()

    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        lambda s: None,
        capture_factory=FlakyFrames,
        game_probe=lambda _: GameProbe(GameStatus.RUNNING, "x", 0),
        process_watcher=lambda pid: None,
        on_error=errors.append,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    assert await _wait(lambda: "" in errors)
    stop.set()

    assert await task is ExitReason.STOPPED
    assert "telemetry read failed" in errors
    assert "" in errors


async def test_reader_reports_bad_frames_and_recovers(monkeypatch):
    _fast(monkeypatch)
    import brake_trainer.telemetry as tel

    calls = {"n": 0}
    real = tel.sample_from_frame

    def flaky(frame):
        calls["n"] += 1
        if calls["n"] <= tel._FRAME_ERROR_LIMIT:
            raise ValueError("bad frame")
        return real(frame)

    monkeypatch.setattr(tel, "sample_from_frame", flaky)
    errors, samples = [], []
    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        samples.append,
        capture_factory=FakeCapture,
        game_probe=lambda _: GameProbe(GameStatus.RUNNING, "x", 0),
        process_watcher=lambda pid: None,
        on_error=errors.append,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    assert await _wait(lambda: bool(samples) and "" in errors)
    stop.set()

    assert await task is ExitReason.STOPPED
    assert tel._ERROR_FRAMES in errors
    assert "" in errors  # a readable frame cleared it
    assert samples

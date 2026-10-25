from __future__ import annotations

import asyncio
import io
import struct
import wave
from types import SimpleNamespace

import pytest

from brake_trainer.audio import AudioPlayer, make_tone
from brake_trainer.config import Settings
from brake_trainer.models import CueKind
from brake_trainer.telemetry import (
    TRACK_LIMITS_NOTE,
    ExitReason,
    GameProbe,
    GameStatus,
    TelemetryReader,
    find_game_process,
    sample_from_frame,
)


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


def test_sample_reads_the_race_cut_fields_from_the_raw_graphics_block():
    raw = bytearray(4096)
    struct.pack_into("<i", raw, 2464, 320)  # race_cut_gained_time_ms
    struct.pack_into("<i", raw, 2468, 150)  # distance_to_deadline
    struct.pack_into("<f", raw, 2472, -0.42)  # race_cut_current_delta
    s = sample_from_frame(frame(graphics_raw=bytes(raw).hex()))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m) == (320, 150)
    assert abs(s.cut_delta_s + 0.42) < 1e-6


def test_sample_ignores_a_short_or_corrupt_raw_graphics_block():
    short = sample_from_frame(frame(graphics_raw="00"))  # too short
    corrupt = sample_from_frame(frame(graphics_raw="zz" * 12))  # 24 chars, not hex
    assert short is not None and short.cut_gained_ms == 0
    assert corrupt is not None and corrupt.cut_gained_ms == 0


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
    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        lambda s: None,
        capture_factory=FakeCapture,
        game_probe=lambda _: next(probes),
        process_watcher=lambda pid: None,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    await asyncio.sleep(0.3)
    assert not task.done()
    stop.set()
    assert await task is ExitReason.STOPPED


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


def test_audio_player_respects_enabled_flag():
    played = []
    holder = {"st": Settings(sound_enabled=False)}
    player = AudioPlayer(lambda: holder["st"], backend=played.append)
    player.play(CueKind.WARN)
    assert played == []
    player.play(CueKind.HERE, force=True)
    import time

    time.sleep(0.1)
    assert len(played) == 1

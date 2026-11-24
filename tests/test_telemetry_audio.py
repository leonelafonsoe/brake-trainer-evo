from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import struct
import sys
import threading
import time
import wave
from types import SimpleNamespace
from typing import Any, cast

import pytest

from brake_trainer.audio import AudioPlayer, _winsound_backend, make_tone
from brake_trainer.config import Settings
from brake_trainer.models import CueKind, Sample
from brake_trainer.telemetry import (
    TRACK_LIMITS_NOTE,
    ExitReason,
    GameProbe,
    GameStatus,
    TelemetryReader,
    _default_config,
    _entry_default,
    _GameWatch,
    _GraphicsReader,
    _LiveCapture,
    _open_graphics_region,
    _resolved_entry,
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
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)  # no graphics bytes


def _frame_with_static(**over: Any) -> Any:
    """``frame()`` with the given fields added to its static block."""
    return frame(static={**frame().static, **over})


def test_sample_appends_a_non_default_track_configuration():
    # Two layouts of one track report the same static.track; the label keeps their learned data
    # apart and is what the Data tab shows.
    s = sample_from_frame(_frame_with_static(track="Brands Hatch", track_configuration="Indy"))
    assert s is not None
    assert s.track == "Brands Hatch [Indy]"


@pytest.mark.parametrize(
    ("track", "configuration"),
    [
        ("Brands Hatch", "gp"),
        ("Brands Hatch", "GP"),
        ("Monza", "v0.4"),
        ("Monza", "GP"),
        ("Spa-Francorchamps", "gp"),
        ("Fuji Speedway GP Short", "GP Short"),
        # The declared default is the catalog entry's, not the layout its name prefers.
        ("Nurburgring Nordschleife", "24h"),
        ("Nordschleife", "24h"),
        ("Nurburgring", "GP"),
    ],
    ids=[
        "brands-hatch-key",
        "brands-hatch-name",
        "monza-name",
        "monza-alias",
        "spa-alias",
        "fuji-layout-name",
        "nordschleife-declared-default",
        "nordschleife-alias-declared-default",
        "nurburgring-gp-declared-default",
    ],
)
def test_sample_keeps_the_raw_name_for_the_default_layout(track, configuration):
    # The game may report the config's key, name or alias. The catalog identifies them all as the
    # default, so existing data keeps loading under the raw game name.
    s = sample_from_frame(_frame_with_static(track=track, track_configuration=configuration))
    assert s is not None
    assert s.track == track


@pytest.mark.parametrize(
    ("track", "configuration", "label"),
    [
        ("Nurburgring Nordschleife", "Nordschleife", "Nurburgring Nordschleife [Nordschleife]"),
        # A repeated label is intentional: the label is the key, so suppressing the suffix would
        # merge this layout with the entry's declared default under one key.
        ("Nordschleife", "Nordschleife", "Nordschleife [Nordschleife]"),
        ("Nurburgring", "Nordschleife", "Nurburgring [Nordschleife]"),
        # A known track whose reported configuration the selector cannot resolve still gets its
        # own key: the fallback uses the track's declared default (24h), so Club is not it.
        ("Nurburgring Nordschleife", "Club", "Nurburgring Nordschleife [Club]"),
    ],
    ids=[
        "nordschleife-layout",
        "nordschleife-repeated",
        "nurburgring-layout",
        "nordschleife-unresolved-config",
    ],
)
def test_sample_suffixes_a_non_default_layout_even_when_the_name_repeats(
    track, configuration, label
):
    s = sample_from_frame(_frame_with_static(track=track, track_configuration=configuration))
    assert s is not None
    assert s.track == label


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({}, "absent"),
        ({"track_configuration": None}, "none"),
        ({"track_configuration": ""}, "empty"),
    ],
)
def test_sample_keeps_the_raw_name_without_a_configuration(over, why):
    s = sample_from_frame(_frame_with_static(track="Brands Hatch", **over))
    assert s is not None, why
    assert s.track == "Brands Hatch", why


def test_sample_keeps_the_raw_name_for_a_track_outside_the_catalog():
    s = sample_from_frame(
        _frame_with_static(track="Nowhere Motor Speedway", track_configuration="Club")
    )
    assert s is not None
    assert s.track == "Nowhere Motor Speedway"


def test_the_catalog_declared_defaults_and_resolution_are_cached():
    _default_config.cache_clear()
    _entry_default.cache_clear()
    _resolved_entry.cache_clear()
    try:
        # The declared default is the entry's own field, not the layout its label prefers.
        assert _default_config("Brands Hatch") == "gp"
        assert _default_config("Nurburgring Nordschleife") == "24h"
        assert _default_config("Nowhere Motor Speedway") == ""
        assert _entry_default("nurburgring_nordschleife") == "24h"
        assert _entry_default("not_a_track") == ""

        first = _default_config.cache_info()
        assert (first.hits, first.misses) == (0, 3)
        assert _default_config("Brands Hatch") == "gp"
        second = _default_config.cache_info()
        assert (second.hits, second.misses) == (first.hits + 1, first.misses)

        # The selector maps a name or alias to the canonical entry and config key.
        assert _resolved_entry("Monza", "v0.4") == ("monza", "v0_4")
        assert _resolved_entry("Monza", "GP") == ("monza", "v0_4")
        assert _resolved_entry("Brands Hatch", "Indy") == ("brands_hatch", "indy")
        assert _resolved_entry("Nurburgring Nordschleife", "Nordschleife") == (
            "nurburgring_nordschleife",
            "nordschleife",
        )
        assert _resolved_entry("Nurburgring Nordschleife", "24h") == (
            "nurburgring_nordschleife",
            "24h",
        )
        assert _resolved_entry("Nowhere Motor Speedway", "Club") == ("", "")
    finally:
        _default_config.cache_clear()
        _entry_default.cache_clear()
        _resolved_entry.cache_clear()


def test_a_missing_track_catalog_keeps_the_raw_name(monkeypatch):
    # A broken or frozen-without-data catalog must degrade to the pre-catalog behaviour, not stop
    # samples. The unique track name keeps the cached "" from poisoning the catalog-backed tests.
    monkeypatch.setitem(sys.modules, "acevo.catalogs", None)
    _default_config.cache_clear()
    _entry_default.cache_clear()
    _resolved_entry.cache_clear()
    try:
        s = sample_from_frame(
            _frame_with_static(track="Catalog Offline Raceway", track_configuration="Club")
        )
        assert s is not None
        assert s.track == "Catalog Offline Raceway"
    finally:
        _default_config.cache_clear()
        _entry_default.cache_clear()
        _resolved_entry.cache_clear()


def test_a_failing_entry_lookup_degrades_to_no_default(monkeypatch):
    import acevo.catalogs

    def boom(_key):
        raise RuntimeError("catalog lookup failed")

    monkeypatch.setattr(acevo.catalogs, "find_track_by_name", boom)
    _default_config.cache_clear()
    _entry_default.cache_clear()
    try:
        assert _entry_default("nurburgring_nordschleife") == ""
    finally:
        _default_config.cache_clear()
        _entry_default.cache_clear()


def _raw_graphics(gained: int, deadline: int, delta: float) -> bytes:
    """The graphics region as the adapter reads it, with the race-cut fields written."""
    raw = bytearray(4096)
    struct.pack_into("<i", raw, 2464, gained)  # race_cut_gained_time_ms
    struct.pack_into("<i", raw, 2468, deadline)  # distance_to_deadline
    struct.pack_into("<f", raw, 2472, delta)  # race_cut_current_delta
    return bytes(raw)


def test_sample_reads_the_race_cut_fields_from_the_raw_graphics_block():
    s = sample_from_frame(frame(), _raw_graphics(320, 150, -0.42))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m) == (320, 150)
    assert abs(s.cut_delta_s + 0.42) < 1e-6


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b"", "no bytes at all"),
        (b"00", "too short"),
        (bytes(2400), "the raw block, cut short before the race-cut fields"),
    ],
)
def test_sample_ignores_a_short_or_corrupt_raw_graphics_block(raw, why):
    s = sample_from_frame(frame(), raw)
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
    s = sample_from_frame(frame(), _raw_graphics(gained, deadline, delta))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)


def test_sample_rejects_a_shifted_but_plausible_looking_race_cut_block():
    # The block moved four bytes earlier in a game update: the read now sees the deadline as the
    # gain (150 ms looks plausible) and the delta's float bits as the deadline, which does not.
    raw = bytearray(4096)
    struct.pack_into("<i", raw, 2460, 320)
    struct.pack_into("<i", raw, 2464, 150)
    struct.pack_into("<f", raw, 2468, -0.42)
    s = sample_from_frame(frame(), bytes(raw))
    assert s is not None
    assert (s.cut_gained_ms, s.cut_deadline_m, s.cut_delta_s) == (0, 0, 0.0)


def test_sample_ignores_the_sdk_graphics_raw_field():
    # acevo-sdk 0.2 nulls graphics_raw in a normal capture, and it is never the source: only the
    # bytes the adapter reads from the graphics region are.
    s = sample_from_frame(frame(graphics_raw=_raw_graphics(320, 150, -0.42)))
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


def _frame_with_state(**state: Any) -> Any:
    """``frame()`` with the given AC state fields added to its graphics block."""
    gfx = frame().graphics
    return frame(graphics={**gfx, **state})


@pytest.mark.parametrize(
    "state",
    [
        {"status": 2, "status_name": "AC_LIVE"},
        {"status": 2},
        {"status_name": "AC_LIVE"},
        {"status_name": "ac_live"},
        {"status": True, "status_name": "AC_LIVE"},  # a bool is not a state code
        {},
        {"status": 2, "focused_car_id": 4, "player_car_id": 4},
        {"status": 2, "focused_car_id": 4},
    ],
    ids=[
        "live-both-fields",
        "live-number",
        "live-name",
        "live-name-any-case",
        "bool-is-not-a-state-code",
        "no-status-field",
        "player-camera",
        "one-id-field-missing",
    ],
)
def test_sample_accepts_a_live_frame(state):
    s = sample_from_frame(_frame_with_state(**state))
    assert s is not None
    assert (s.track, s.car, s.pos) == ("Monza", "Ferrari 296 GTB", 0.42)


@pytest.mark.parametrize(
    "state",
    [
        {"status": 0, "status_name": "AC_OFF"},
        {"status": 0},
        {"status_name": "AC_OFF"},
        {"status": 1, "status_name": "AC_REPLAY"},
        {"status_name": "AC_REPLAY"},
        {"status": 3, "status_name": "AC_PAUSE"},
        {"status": 3},
        {"status_name": "AC_PAUSE"},
        {"status": 1, "status_name": "AC_LIVE"},  # the numeric field wins
        {"status_name": "SOME_FUTURE_STATE"},
        {"status": 2, "status_name": "AC_LIVE", "focused_car_id": 3, "player_car_id": 1},
        {"focused_car_id": 3, "player_car_id": 1},
        {"status": 2, "focused_car_id": 3, "player_car_id": 1},
    ],
    ids=[
        "off-both-fields",
        "off-number",
        "off-name",
        "replay-both-fields",
        "replay-name-only",
        "pause-both-fields",
        "pause-number",
        "pause-name",
        "numeric-status-wins",
        "unknown-name",
        "spectating-a-live-session",
        "spectating-without-a-status-field",
        "spectating-numeric-status",
    ],
)
def test_sample_rejects_frames_that_are_not_live(state):
    assert sample_from_frame(_frame_with_state(**state)) is None


async def test_the_sdk_still_arms_the_frame_gate_after_start():
    # Tripwire for the T1 workaround: if a future acevo-sdk streams frames without a lap boundary,
    # drop ``_LiveCapture`` and this test rather than keeping a stale private-attribute patch.
    from acevo import TelemetryCapture

    capture = TelemetryCapture(hz=1)
    try:
        assert await capture.start_capture() is True
        assert capture._recording_awaiting_boundary is True
    finally:
        await capture.stop_capture()


def test_the_sdk_still_publishes_the_graphics_region():
    from acevo.capture import REGIONS

    name, size = REGIONS["graphics"]
    assert name
    assert size > 0


async def test_the_live_capture_releases_the_frame_gate():
    class Inner:
        def __init__(self):
            self._recording_awaiting_boundary = True

        async def start_capture(self):
            return True

    inner = Inner()
    assert await _LiveCapture(inner).start_capture() is True
    assert inner._recording_awaiting_boundary is False


async def test_the_live_capture_delegates_the_capture_api():
    class Recorder:
        def __init__(self):
            self.calls = []
            self._recording_awaiting_boundary = True

        async def start_capture(self):
            self.calls.append("start_capture")
            return True

        def is_capturing(self):
            self.calls.append("is_capturing")
            return True

        def get_stop_reason(self):
            self.calls.append("get_stop_reason")
            return "heartbeat_timeout"

        def get_frames(self):
            self.calls.append("get_frames")
            return ["frame"]

        def clear(self):
            self.calls.append("clear")

        async def stop_capture(self):
            self.calls.append("stop_capture")
            return ["frame"]

        def get_metadata(self):
            self.calls.append("get_metadata")
            return "metadata"

    inner = Recorder()
    capture = _LiveCapture(inner)
    assert await capture.start_capture() is True
    assert capture.is_capturing() is True
    assert capture.get_stop_reason() == "heartbeat_timeout"
    assert capture.get_frames() == ["frame"]
    capture.clear()
    assert await capture.stop_capture() == ["frame"]
    assert capture.get_metadata() == "metadata"
    assert inner.calls == [
        "start_capture",
        "is_capturing",
        "get_stop_reason",
        "get_frames",
        "clear",
        "stop_capture",
        "get_metadata",
    ]


def test_graphics_reader_reads_once_open():
    opens: list[int] = []

    class Region:
        def read_raw(self):
            return b"graphics"

        def close(self):
            pass

    def open_reader():
        opens.append(1)
        return Region()

    reader = _GraphicsReader(open_reader=open_reader)
    assert reader.read() == b"graphics"
    assert reader.read() == b"graphics"
    assert len(opens) == 1
    reader.close()


def test_graphics_reader_retries_a_failed_open_at_most_once_a_second():
    attempts: list[int] = []
    now = [100.0]

    def open_reader():
        attempts.append(1)
        return None

    reader = _GraphicsReader(open_reader=open_reader, clock=lambda: now[0])
    assert reader.read() is None
    assert len(attempts) == 1

    now[0] += 0.5
    assert reader.read() is None
    assert len(attempts) == 1  # too soon: no new open

    now[0] += 0.5
    assert reader.read() is None
    assert len(attempts) == 2


def test_graphics_reader_reopens_after_a_failed_read():
    regions: list[Any] = []
    calls = {"n": 0}

    class Region:
        def __init__(self):
            self.closed = False

        def read_raw(self):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("the game recreated the mapping")
            return b"graphics"

        def close(self):
            self.closed = True

    def open_reader():
        region = Region()
        regions.append(region)
        return region

    reader = _GraphicsReader(open_reader=open_reader)
    assert reader.read() == b"graphics"
    assert reader.read() is None
    assert regions[0].closed
    assert reader.read() == b"graphics"
    assert len(regions) == 2
    reader.close()
    assert regions[1].closed


def test_graphics_reader_close_is_idempotent():
    closes: list[int] = []

    class Region:
        def read_raw(self):
            return b""

        def close(self):
            closes.append(1)

    reader = _GraphicsReader(open_reader=Region)
    reader.read()
    reader.close()
    reader.close()
    assert closes == [1]


def test_open_graphics_region_reports_a_missing_region(monkeypatch):
    import acevo

    class MissingRegion:
        def __init__(self, name, size):
            pass

        def open(self):
            return False

    monkeypatch.setattr(acevo, "RegionReader", MissingRegion)
    assert _open_graphics_region() is None


def test_open_graphics_region_survives_a_missing_sdk_symbol(monkeypatch):
    # A future SDK that moves or removes the reader symbol must degrade to "no cut data", not end
    # the reader loop with an ImportError.
    import acevo

    monkeypatch.delattr(acevo, "RegionReader")
    assert _open_graphics_region() is None


def test_open_graphics_region_returns_an_open_reader(monkeypatch):
    import acevo
    from acevo.capture import REGIONS

    opened: list[tuple[str, int]] = []

    class FakeRegion:
        def __init__(self, name, size):
            opened.append((name, size))

        def open(self):
            return True

    monkeypatch.setattr(acevo, "RegionReader", FakeRegion)
    reader = _open_graphics_region()
    assert reader is not None
    assert opened == [REGIONS["graphics"]]


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
        return True

    async def stop_capture(self):
        self.running = False

    def is_capturing(self):
        self.polls += 1
        if self.index == 0 and self.polls > 3:
            self.running = False  # SDK stops by itself, e.g. heartbeat timeout
        return self.running

    def get_stop_reason(self):
        return "heartbeat_timeout"

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
    probe_calls: list[int] = []
    samples: list[Sample] = []
    restarts: list[int] = []
    states: list[bool] = []
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

    def probe(name: str) -> GameProbe:
        calls.append(name)
        return probes.pop(0)

    watch = _GameWatch(
        probe,
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
    states: list[bool] = []
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
    from brake_trainer.telemetry import open_process_watcher

    if sys.platform != "win32":
        assert open_process_watcher(1234) is None
    assert open_process_watcher(0) is None


@pytest.mark.skipif(sys.platform != "win32", reason="opens a real Windows process handle")
def test_open_process_watcher_tracks_a_running_process_on_windows():
    from brake_trainer.telemetry import open_process_watcher

    watcher = open_process_watcher(os.getpid())
    assert watcher is not None
    try:
        assert watcher.exited() is False  # this test process is still running
    finally:
        watcher.close()


@pytest.mark.skipif(sys.platform != "win32", reason="plays through the real winsound module")
def test_the_winsound_backend_plays_the_generated_wav_from_memory(monkeypatch):
    import winsound

    played: list[tuple[bytes, int]] = []
    monkeypatch.setattr(winsound, "PlaySound", lambda wav, flags: played.append((wav, flags)))

    wav = make_tone(880, 90, 0.4)
    _winsound_backend(wav)

    assert played == [(wav, cast(Any, winsound).SND_MEMORY)]


def test_make_tone_is_valid_wav_and_volume_scales():
    quiet, loud = make_tone(1000, 50, 0.1), make_tone(1000, 50, 1.0)
    with wave.open(io.BytesIO(loud)) as w:
        assert w.getnframes() == int(22050 * 0.05)

    def peak(wav: bytes) -> int:
        samples = struct.unpack(f"<{(len(wav) - 44) // 2}h", wav[44:])
        return int(max(abs(x) for x in samples))

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

    monkeypatch.setattr(threading, "Thread", InlineThread)
    with caplog.at_level(logging.ERROR, logger="brake_trainer.audio"):
        player.play(CueKind.WARN, force=True)  # the failure is logged, not raised
    assert "Could not play cue" in caplog.text


async def test_reader_reports_a_capture_start_failure_and_recovers(monkeypatch):
    _fast(monkeypatch)
    attempts: list[int] = []
    errors: list[str] = []

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
    errors: list[str] = []

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

    def flaky(frame, raw_graphics=None):
        calls["n"] += 1
        if calls["n"] <= tel._FRAME_ERROR_LIMIT:
            raise ValueError("bad frame")
        return real(frame, raw_graphics)

    monkeypatch.setattr(tel, "sample_from_frame", flaky)
    errors: list[str] = []
    samples: list[Sample] = []
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


async def test_reader_attaches_the_live_race_cut_to_every_sample(monkeypatch):
    _fast(monkeypatch)
    polls = {"frames": 0}

    class LiveGraphics:
        def __init__(self):
            self.reads = 0
            self.closed = 0

        def read(self):
            self.reads += 1
            return _raw_graphics(320, 150, -0.42)

        def close(self):
            self.closed += 1

    class TwoFrames(FakeCapture):
        def is_capturing(self):
            return self.running

        def get_frames(self):
            polls["frames"] += 1
            return [frame(), frame()]

    graphics = LiveGraphics()
    samples: list[Sample] = []
    stop = asyncio.Event()
    reader = TelemetryReader(
        lambda: Settings(),
        samples.append,
        capture_factory=TwoFrames,
        game_probe=lambda _: GameProbe(GameStatus.RUNNING, "x", 0),
        process_watcher=lambda pid: None,
        graphics_reader=lambda: graphics,
        poll_s=0.001,
    )
    task = asyncio.create_task(reader.run(stop))
    assert await _wait(lambda: len(samples) >= 2)
    stop.set()

    assert await task is ExitReason.STOPPED
    assert all((s.cut_gained_ms, s.cut_deadline_m) == (320, 150) for s in samples)
    assert all(abs(s.cut_delta_s + 0.42) < 1e-6 for s in samples)
    assert graphics.reads == polls["frames"]  # at most once per poll, and only when frames arrive
    assert graphics.closed == 1  # the mapping is released when the reader exits

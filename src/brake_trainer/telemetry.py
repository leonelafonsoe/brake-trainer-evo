"""Telemetry source: reads Assetto Corsa EVO through ``acevo-sdk`` and watches the game process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import struct
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from functools import cache
from typing import Any, NamedTuple, Protocol

from .config import Settings
from .models import RACE_CUT_MAX_DEADLINE_M, RACE_CUT_MAX_GAINED_MS, Sample

log = logging.getLogger(__name__)

_PROBE_WAITING_S = 3.0  # looking for the game to start
_PROBE_FALLBACK_S = 1.0  # watching a running game we could not open a handle to
_GAME_MISSING_CHECKS = 2  # consecutive misses (fallback mode) before the game counts as closed
_RESTART_DELAY_S = 2.0
_MAX_RESTART_DELAY_S = 30.0  # cap for the retry backoff after a failure
_FRAME_ERROR_LIMIT = 3  # consecutive bad frames before the UI is told

# Short user-facing failures: the exception detail goes to the log, not the status line.
_ERROR_START = "capture could not start"
_ERROR_READ = "telemetry read failed"
_ERROR_FRAMES = "telemetry frames could not be read"

# The graphics block carries the game's "race cut" fields, its own record of the last off-track:
# the time it judged the driver gained, and how far they still have to drive to give it back. The
# SDK decodes the graphics region but does not surface these three, and acevo-sdk 0.2 drops the raw
# region bytes from a normal capture, so the adapter reads the graphics mapping itself through the
# SDK's ``RegionReader``. The offsets are the ones its offset table already defines; they are an
# assumption the SDK does not publish, so every read is checked against the plausibility bounds in
# ``models`` before it reaches the engine.
_GFX_RACE_CUT_OFFSET = 2464  # race_cut_gained_time_ms (int32), then distance_to_deadline (int32)
_GFX_RACE_CUT_BYTES = 12  # ...then race_cut_current_delta (float32)

# Said once at start-up, so the app's limits with track limits are never a silent surprise.
TRACK_LIMITS_NOTE = (
    "Track limits come from the game: each cut in its log and its race-cut pair drop the sector "
    "they happened in. Its one-shot 'is_valid_lap' flag is the fallback when no per-cut signal is "
    "available, and then only the sector where the flag fell is dropped."
)


class GameStatus(Enum):
    RUNNING = "running"
    ABSENT = "absent"
    UNKNOWN = "unknown"  # couldn't list processes


class ExitReason(Enum):
    STOPPED = "stopped"
    GAME_CLOSED = "game_closed"


class GameProbe(NamedTuple):
    status: GameStatus
    name: str = ""
    pid: int = 0


class ProcessWatcher(Protocol):
    def exited(self) -> bool: ...

    def close(self) -> None: ...


class _WinProcessWatcher:
    """Watches one process through a Windows handle: exit is noticed instantly, no polling."""

    def __init__(self, kernel32: Any, handle: Any) -> None:
        self._k32, self._handle = kernel32, handle

    def exited(self) -> bool:
        return bool(self._k32.WaitForSingleObject(self._handle, 0) == 0)  # WAIT_OBJECT_0

    def close(self) -> None:
        self._k32.CloseHandle(self._handle)


def open_process_watcher(pid: int) -> ProcessWatcher | None:
    """A watcher for ``pid``, or None when unsupported / not permitted (the caller then polls)."""
    if sys.platform != "win32" or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    except Exception:
        return None
    return _WinProcessWatcher(k32, handle) if handle else None


def find_game_process(fragment: str, run: Callable[..., Any] = subprocess.run) -> GameProbe:
    """Is a process whose name contains ``fragment`` running? Returns its name and pid if so."""
    if not fragment.strip():
        # An empty name would match the first row of the task list (System), which would then be
        # watched as if it were the game. Say "unknown" instead: the reader never closes on that.
        return GameProbe(GameStatus.UNKNOWN)
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        out = run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        ).stdout
    except Exception:
        return GameProbe(GameStatus.UNKNOWN)
    for line in out.splitlines():
        cells = line.strip().strip('"').split('","')
        if cells and fragment.lower() in cells[0].lower():
            pid = int(cells[1]) if len(cells) > 1 and cells[1].isdigit() else 0
            return GameProbe(GameStatus.RUNNING, cells[0], pid)
    return GameProbe(GameStatus.ABSENT)


def _frame_time(frame: Any) -> float:
    stamp = getattr(frame, "timestamp", None)
    try:
        if isinstance(stamp, str):
            return datetime.fromisoformat(stamp).timestamp()
        if isinstance(stamp, datetime):
            return stamp.timestamp()
    except ValueError:
        pass
    return time.time()


def _race_cut(raw: bytes | None) -> tuple[int, int, float]:
    """The game's race-cut fields from the raw graphics bytes: (gained_ms, deadline_m, delta_s).

    All zero when the game has not flagged an off-track, when the region is not there yet, or when
    the decoded values are not plausible. The offsets are not published by the SDK, so a shifted
    block could otherwise look like a cut and drop sectors continuously; a plausible gain, a
    sane give-back distance and a finite delta are what the game's own record looks like.
    """
    if not raw:
        return 0, 0, 0.0
    chunk = raw[_GFX_RACE_CUT_OFFSET : _GFX_RACE_CUT_OFFSET + _GFX_RACE_CUT_BYTES]
    if len(chunk) < _GFX_RACE_CUT_BYTES:
        return 0, 0, 0.0
    gained, deadline, delta = struct.unpack("<iif", chunk)
    if not (
        1 <= gained <= RACE_CUT_MAX_GAINED_MS
        and 0 <= deadline <= RACE_CUT_MAX_DEADLINE_M
        and math.isfinite(delta)
    ):
        return 0, 0, 0.0
    return gained, deadline, delta


def _live_frame(gfx: Mapping[str, Any]) -> bool:
    """Is the graphics block showing a live session?

    A replay, a pause or the teardown still carries a position and a track, so learning it would
    teach braking points from a lap the driver is not driving. The SDK's 0.2 state model names the
    states (``status`` 0 OFF, 1 REPLAY, 2 LIVE, 3 PAUSE); a build without the field is assumed live
    so older captures keep working.
    """
    status = gfx.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        return status == 2  # AC_LIVE
    name = gfx.get("status_name")
    if isinstance(name, str) and name:
        return name.upper() == "AC_LIVE"
    return True


@cache
def _resolved_entry(track: str, configuration: str) -> tuple[str, str]:
    """The catalog entry and config key a reported pair resolves to, or ``("", "")``.

    The game may report a configuration's key, its name or one of its aliases (``v0.4`` and ``GP``
    both name Monza's only layout), and a track name may identify a separate catalog entry. The
    SDK's selector resolves all of that, so raw string comparison would suffix a default layout and
    orphan the user's existing learned data.
    """
    try:
        from acevo.catalogs import select_track_profile

        entry, profile = select_track_profile(track_name=track, config_name=configuration)
        if not entry or not profile:
            return "", ""
        return str(entry), str(profile.get("config_key") or "")
    except Exception:
        log.debug("Could not resolve %r for track %r", configuration, track, exc_info=True)
        return "", ""


@cache
def _entry_default(entry_key: str) -> str:
    """The catalog entry's declared default configuration, or "" when it cannot tell."""
    try:
        from acevo.catalogs import find_track_by_name

        _, profile = find_track_by_name(entry_key)
        return str(profile.get("config_key") or "") if profile else ""
    except Exception:
        log.debug("Could not read the default for catalog entry %r", entry_key, exc_info=True)
        return ""


@cache
def _default_config(track: str) -> str:
    """The declared default configuration for ``track``, or "" when the catalog cannot tell.

    Used only as the fallback when a reported configuration does not resolve. It must be the
    catalog entry's declared default, not the layout the track label happens to name: the SDK's
    selector prefers the named layout, which differs for e.g. Nurburgring Nordschleife.

    The catalog travels with ``acevo-sdk`` as package data. A frozen build without that data, a
    future SDK that moves the helpers, or a track the catalog does not know must all keep keying
    learned data on the raw game name, so the lookup is lazy and failure-safe and the catalog is
    never imported until a sample actually needs a label.
    """
    try:
        from acevo.catalogs import resolve_track_key

        key = resolve_track_key(track)
        return _entry_default(key) if key else ""
    except Exception:
        log.debug("Could not resolve the track configuration for %r", track, exc_info=True)
        return ""


def _track_label(track: str, configuration: str) -> str:
    """The learned-data key and display label for a track and its game configuration.

    The default layout keeps the raw game name, so existing files load unchanged. An alternate
    layout appends its configuration (``Brands Hatch [Indy]``) and starts its own entry. A track
    the catalog cannot resolve also keeps the raw name: guessing would be worse than the old
    behaviour, where its layouts share one key.

    The label is also the store key, so a repeated ``Track [Config]`` (for example ``Nordschleife
    [Nordschleife]``) is intentional: suppressing it would merge that layout with the resolved
    entry's default under one key.
    """
    if not configuration:
        return track
    entry, resolved = _resolved_entry(track, configuration)
    if entry and resolved:
        return track if resolved == _entry_default(entry) else f"{track} [{configuration}]"
    default = _default_config(track)
    if not default:
        return track
    return f"{track} [{configuration}]"


def sample_from_frame(frame: Any, raw_graphics: bytes | None = None) -> Sample | None:
    """Reduce an SDK frame to a :class:`Sample`; None if the game isn't in a session."""
    gfx = getattr(frame, "graphics", None) or {}
    phys = getattr(frame, "physics", None) or {}
    stat = getattr(frame, "static", None) or {}
    if not all(isinstance(x, Mapping) for x in (gfx, phys, stat)):
        return None
    if gfx.get("error") or phys.get("error") or "normalized_car_position" not in gfx:
        return None
    if not _live_frame(gfx):
        return None
    track = stat.get("track")
    car = gfx.get("car_model") or stat.get("car_model")
    if not track or not car:  # menus, loading screens
        return None
    configuration = stat.get("track_configuration") or ""
    length = stat.get("track_length_m") or (gfx.get("lap_length_km") or 0) * 1000 or None
    gained, deadline, delta = _race_cut(raw_graphics)
    return Sample(
        track=_track_label(str(track), str(configuration)),
        car=str(car),
        length_m=float(length) if length else None,
        pos=float(gfx["normalized_car_position"]),
        brake=float(phys.get("brake", 0.0)),
        speed_kmh=float(phys.get("speed_kmh", 0.0)),
        in_pit=bool(gfx.get("is_in_pit_lane") or gfx.get("is_in_pit")),
        t=_frame_time(frame),
        lap_valid=bool(gfx.get("is_valid_lap", True)),
        cut_gained_ms=gained,
        cut_deadline_m=deadline,
        cut_delta_s=delta,
        timing_invalid=bool(gfx.get("is_invalid")),
    )


class _GraphicsSource(Protocol):
    """The slice of the SDK's region reader the telemetry loop needs."""

    def read(self) -> bytes | None: ...

    def close(self) -> None: ...


_GRAPHICS_RETRY_S = 1.0  # a failed graphics-region open is retried no faster than this


def _open_graphics_region() -> Any | None:
    """Open the game's graphics shared-memory region, or None when it is not published yet."""
    try:
        from acevo import RegionReader
        from acevo.capture import REGIONS

        reader = RegionReader(*REGIONS["graphics"])
        return reader if reader.open() else None
    except Exception:
        # Includes a missing symbol in a future SDK: the reader degrades to "no cut data".
        log.debug("Could not open the graphics region", exc_info=True)
        return None


class _GraphicsReader(_GraphicsSource):
    """Lazily reads the graphics region, reopening it when the game republishes it.

    acevo-sdk 0.2 drops ``graphics_raw`` from a normal capture, but the race-cut fields are not
    decoded, so it reads the same mapping through the SDK's own ``RegionReader``. Opens are lazy
    and rate-limited: the game creates the region some time after the capture starts.
    """

    def __init__(
        self,
        open_reader: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._open_reader = open_reader or _open_graphics_region
        self._clock = clock
        self._reader: Any = None
        self._last_attempt: float | None = None

    def read(self) -> bytes | None:
        if self._reader is None:
            now = self._clock()
            if self._last_attempt is not None and now - self._last_attempt < _GRAPHICS_RETRY_S:
                return None
            self._last_attempt = now
            try:
                self._reader = self._open_reader()
            except Exception:
                self._reader = None
            if self._reader is None:
                return None
        try:
            return bytes(self._reader.read_raw())
        except Exception:
            # The game may have recreated the mapping: close it and reopen on the next poll.
            self.close()
            return None

    def close(self) -> None:
        reader, self._reader = self._reader, None
        self._last_attempt = None
        if reader is not None:
            with contextlib.suppress(Exception):
                reader.close()


class _LiveCapture:
    """The default capture, released from the 0.2 lap-boundary frame gate."""

    def __init__(self, capture: Any) -> None:
        self._capture = capture

    async def start_capture(self) -> bool:
        started = await self._capture.start_capture()
        # acevo-sdk 0.2.2 ``TelemetryCapture.start_capture`` (capture.py:948) arms
        # ``_recording_awaiting_boundary``; the loop then appends no frame until the next clean lap
        # boundary clears it. The live overlay and learning need the outlap, so release the gate.
        self._capture._recording_awaiting_boundary = False
        return bool(started)

    def is_capturing(self) -> bool:
        return bool(self._capture.is_capturing())

    def get_stop_reason(self) -> str | None:
        reason = self._capture.get_stop_reason()
        return reason if isinstance(reason, str) else None

    def get_frames(self) -> Any:
        return self._capture.get_frames()

    def clear(self) -> None:
        self._capture.clear()

    async def stop_capture(self) -> Any:
        return await self._capture.stop_capture()

    def get_metadata(self) -> Any:
        return self._capture.get_metadata()


def _default_capture_factory(hz: float) -> Any:
    from acevo import TelemetryCapture

    return _LiveCapture(TelemetryCapture(hz=hz))


async def _wait_or_stop(stop: asyncio.Event, delay: float) -> bool:
    """Wait up to ``delay``; return True when stop is requested instead of the timeout."""
    if delay <= 0:
        return stop.is_set()
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


class _WatchResult(NamedTuple):
    detected: str = ""  # the game's process name, when it was first seen
    closed: bool = False


class _GameWatch:
    """One game-process watch: a handle when one can be opened, ``tasklist`` polling otherwise."""

    def __init__(
        self,
        probe: Callable[[str], GameProbe],
        open_watcher: Callable[[int], ProcessWatcher | None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probe = probe
        self._open_watcher = open_watcher
        self._clock = clock
        self._watcher: ProcessWatcher | None = None
        self._seen = False
        self._missing = 0
        self._last_check = 0.0

    async def poll(self, process_name: str) -> _WatchResult:
        """Check once, at the waiting or fallback cadence, and report a detection or exit."""
        if self._watcher is not None:
            return _WatchResult(closed=self._watcher.exited())
        now = self._clock()
        interval = _PROBE_FALLBACK_S if self._seen else _PROBE_WAITING_S
        if now - self._last_check < interval:
            return _WatchResult()
        self._last_check = now
        probe = await asyncio.to_thread(self._probe, process_name)
        if probe.status is GameStatus.RUNNING:
            detected = "" if self._seen else probe.name
            self._seen, self._missing = True, 0
            self._watcher = self._open_watcher(probe.pid) if probe.pid else None
            return _WatchResult(detected=detected)
        if probe.status is GameStatus.ABSENT and self._seen:
            self._missing += 1
            if self._missing >= _GAME_MISSING_CHECKS:
                return _WatchResult(closed=True)
        return _WatchResult()

    def close(self) -> None:
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None


class TelemetryReader:
    """Async loop: capture -> samples, with automatic restart and game-exit detection."""

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        on_sample: Callable[[Sample], None],
        on_message: Callable[[str], None] = lambda text: None,
        on_game_state: Callable[[bool], None] = lambda running: None,
        *,
        on_error: Callable[[str], None] = lambda text: None,
        capture_factory: Callable[[float], Any] = _default_capture_factory,
        game_probe: Callable[[str], GameProbe] = find_game_process,
        process_watcher: Callable[[int], ProcessWatcher | None] = open_process_watcher,
        on_restart: Callable[[], None] = lambda: None,
        poll_s: float = 0.1,
        graphics_reader: Callable[[], _GraphicsSource] = _GraphicsReader,
    ) -> None:
        self._get_settings = get_settings
        self._on_sample = on_sample
        self._on_message = on_message
        self._on_game_state = on_game_state
        self._on_error = on_error
        self._capture_factory = capture_factory
        self._probe = game_probe
        self._open_watcher = process_watcher
        self._on_restart = on_restart
        self._poll_s = poll_s
        self._graphics_reader = graphics_reader
        self._bad_frames = 0
        self._frame_failed = False

    async def run(self, stop: asyncio.Event) -> ExitReason:
        """Capture until stopped or the game closes, retrying failures with a backoff.

        A capture that cannot start, a poll that raises, or a burst of unreadable frames must not
        end the worker: the overlay would wait forever with no explanation. Report the failure,
        wait (doubling the delay up to a cap), and try again. The game-watch state survives a
        capture restart, so a retry does not probe for the game again.
        """
        delay = _RESTART_DELAY_S
        watch = _GameWatch(self._probe, self._open_watcher)
        cap: Any = None
        graphics: _GraphicsSource | None = None
        logged_regions = False
        try:
            while not stop.is_set():
                if cap is None:
                    try:
                        cap = self._capture_factory(self._get_settings().telemetry_hz)
                        started = await cap.start_capture()
                    except Exception:
                        log.exception("Telemetry failed: %s", _ERROR_START)
                        self._on_error(_ERROR_START)
                        if await _wait_or_stop(stop, delay):
                            break
                        delay = min(delay * 2, _MAX_RESTART_DELAY_S)
                        continue
                    if started:
                        graphics = self._graphics_reader()
                    self._on_error("")  # a previous start or read failure is over
                    self._on_message("Waiting for the game...")
                    logged_regions = False
                    delay = _RESTART_DELAY_S

                try:
                    await asyncio.sleep(self._poll_s)
                    if not cap.is_capturing():
                        self._on_message(f"Telemetry stopped ({cap.get_stop_reason()}); restarting")
                        await self._stop_capture(cap)
                        self._close_graphics(graphics)
                        graphics = None
                        cap = None
                        self._on_restart()
                        if await _wait_or_stop(stop, _RESTART_DELAY_S):
                            break
                        continue

                    frames = cap.get_frames()
                    cap.clear()  # keep memory flat
                    raw_graphics = graphics.read() if frames and graphics is not None else None
                    if frames and not logged_regions:
                        logged_regions = True
                        self._log_regions(cap)
                    self._deliver(frames, raw_graphics)

                    # Game exit. With a process handle it is noticed on the next poll (~0.1 s);
                    # without one we fall back to listing processes once a second.
                    watched = await watch.poll(self._get_settings().game_process)
                    if watched.detected:
                        self._on_message(f"Game detected ({watched.detected})")
                        self._on_game_state(True)
                    if watched.closed:
                        return self._game_closed()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Telemetry read failed")
                    self._on_error(_ERROR_READ)
                    await self._stop_capture(cap)
                    self._close_graphics(graphics)
                    graphics = None
                    cap = None
                    if await _wait_or_stop(stop, delay):
                        break
                    delay = min(delay * 2, _MAX_RESTART_DELAY_S)
            return ExitReason.STOPPED
        finally:
            watch.close()
            self._close_graphics(graphics)
            if cap is not None:
                await self._stop_capture(cap)

    @staticmethod
    async def _stop_capture(cap: Any) -> None:
        with contextlib.suppress(Exception):
            await cap.stop_capture()

    @staticmethod
    def _close_graphics(graphics: _GraphicsSource | None) -> None:
        if graphics is not None:
            with contextlib.suppress(Exception):
                graphics.close()

    def _deliver(self, frames: Any, raw_graphics: bytes | None = None) -> None:
        """Turn frames into samples; one bad frame must not end the session."""
        for frame in frames:
            try:
                sample = sample_from_frame(frame, raw_graphics)
            except Exception:
                self._bad_frames += 1
                log.exception("Could not read a telemetry frame")
                if self._bad_frames == _FRAME_ERROR_LIMIT:
                    self._frame_failed = True
                    self._on_error(_ERROR_FRAMES)
                continue
            self._bad_frames = 0
            if self._frame_failed:
                self._frame_failed = False
                self._on_error("")  # frames are readable again
            if sample is not None:
                self._on_sample(sample)

    def _game_closed(self) -> ExitReason:
        self._on_game_state(False)
        self._on_message("Game closed")
        return ExitReason.GAME_CLOSED

    @staticmethod
    def _log_regions(cap: Any) -> None:
        """Once per capture, note which shared-memory regions the SDK attached to.

        Verbose only, and only useful in a report: it tells "the game publishes nothing on this
        field" apart from "the region was not attached".
        """
        get_metadata = getattr(cap, "get_metadata", None)
        meta = get_metadata() if callable(get_metadata) else None
        log.debug("telemetry attached: regions=%s", getattr(meta, "regions_found", None))

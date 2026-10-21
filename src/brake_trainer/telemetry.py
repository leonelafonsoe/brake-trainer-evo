"""Telemetry source: reads Assetto Corsa EVO through ``acevo-sdk`` and watches the game process."""

from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Any, NamedTuple, Protocol

from .config import Settings
from .models import Sample

log = logging.getLogger(__name__)

_PROBE_WAITING_S = 3.0  # looking for the game to start
_PROBE_FALLBACK_S = 1.0  # watching a running game we could not open a handle to
_GAME_MISSING_CHECKS = 2  # consecutive misses (fallback mode) before the game counts as closed
_RESTART_DELAY_S = 2.0

# The graphics block carries the game's "race cut" fields, its own record of the last off-track:
# the time it judged the driver gained, and how far they still have to drive to give it back. The
# SDK decodes the graphics region but does not surface these three, so they are read from the raw
# bytes (``FrameData.graphics_raw``) at the offsets its offset table already defines.
_GFX_RACE_CUT_OFFSET = 2464  # race_cut_gained_time_ms (int32), then distance_to_deadline (int32)
_GFX_RACE_CUT_BYTES = 12  # ...then race_cut_current_delta (float32)

# Said once at start-up, so the app's limits with track limits are never a silent surprise.
TRACK_LIMITS_NOTE = (
    "Track limits come from the game: each cut in its log, its race-cut pair and its live count of "
    "tyres off the track drop the sector they happened in. Its one-shot 'is_valid_lap' flag is the "
    "fallback when no per-cut signal is available, and then only the sector where the flag fell is "
    "dropped."
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


def _race_cut(frame: Any) -> tuple[int, int, float]:
    """The game's race-cut fields from the raw graphics bytes: (gained_ms, deadline_m, delta_s).

    All zero when the game has not flagged an off-track (or when the region is not there yet).
    """
    raw = getattr(frame, "graphics_raw", None)
    if not raw:
        return 0, 0, 0.0
    start = _GFX_RACE_CUT_OFFSET * 2  # hex: two characters per byte
    chunk = raw[start : start + _GFX_RACE_CUT_BYTES * 2]
    if len(chunk) < _GFX_RACE_CUT_BYTES * 2:
        return 0, 0, 0.0
    try:
        data = bytes.fromhex(chunk)
    except ValueError:
        return 0, 0, 0.0
    gained = int.from_bytes(data[0:4], "little", signed=True)
    deadline = int.from_bytes(data[4:8], "little", signed=True)
    return gained, deadline, struct.unpack_from("<f", data, 8)[0]


def sample_from_frame(frame: Any) -> Sample | None:
    """Reduce an SDK frame to a :class:`Sample`; None if the game isn't in a session."""
    gfx = getattr(frame, "graphics", None) or {}
    phys = getattr(frame, "physics", None) or {}
    stat = getattr(frame, "static", None) or {}
    if not all(isinstance(x, Mapping) for x in (gfx, phys, stat)):
        return None
    if gfx.get("error") or phys.get("error") or "normalized_car_position" not in gfx:
        return None
    track = stat.get("track")
    car = gfx.get("car_model") or stat.get("car_model")
    if not track or not car:  # menus, loading screens
        return None
    length = stat.get("track_length_m") or (gfx.get("lap_length_km") or 0) * 1000 or None
    gained, deadline, delta = _race_cut(frame)
    return Sample(
        track=str(track),
        car=str(car),
        length_m=float(length) if length else None,
        pos=float(gfx["normalized_car_position"]),
        brake=float(phys.get("brake", 0.0)),
        speed_kmh=float(phys.get("speed_kmh", 0.0)),
        in_pit=bool(gfx.get("is_in_pit_lane") or gfx.get("is_in_pit")),
        t=_frame_time(frame),
        lap_valid=bool(gfx.get("is_valid_lap", True)),
        tyres_out=int(phys.get("number_of_tyres_out", 0) or 0),
        cut_gained_ms=gained,
        cut_deadline_m=deadline,
        cut_delta_s=delta,
        timing_invalid=bool(gfx.get("is_invalid")),
    )


def _default_capture_factory(hz: float) -> Any:
    from acevo import TelemetryCapture

    # The SDK stops capturing after 120 s standing still before the first lap (pits, online
    # lobby). Switch that off; the reader restarts capture if anything else stops it.
    TelemetryCapture.IDLE_TIMEOUT_SECONDS = float("inf")
    return TelemetryCapture(hz=hz)


class TelemetryReader:
    """Async loop: capture -> samples, with automatic restart and game-exit detection."""

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        on_sample: Callable[[Sample], None],
        on_message: Callable[[str], None] = lambda text: None,
        on_game_state: Callable[[bool], None] = lambda running: None,
        *,
        capture_factory: Callable[[float], Any] = _default_capture_factory,
        game_probe: Callable[[str], GameProbe] = find_game_process,
        process_watcher: Callable[[int], ProcessWatcher | None] = open_process_watcher,
        on_restart: Callable[[], None] = lambda: None,
        poll_s: float = 0.1,
    ) -> None:
        self._get_settings = get_settings
        self._on_sample = on_sample
        self._on_message = on_message
        self._on_game_state = on_game_state
        self._capture_factory = capture_factory
        self._probe = game_probe
        self._open_watcher = process_watcher
        self._on_restart = on_restart
        self._poll_s = poll_s

    async def run(self, stop: asyncio.Event) -> ExitReason:
        cap = self._capture_factory(self._get_settings().telemetry_hz)
        await cap.start_capture()
        self._on_message("Waiting for the game...")
        last_check, seen, missing = 0.0, False, 0
        watcher: ProcessWatcher | None = None
        logged_regions = False
        try:
            while not stop.is_set():
                await asyncio.sleep(self._poll_s)
                if not cap.is_capturing():
                    self._on_message(f"Telemetry stopped ({cap.get_stop_reason()}); restarting")
                    await asyncio.sleep(_RESTART_DELAY_S)
                    cap = self._capture_factory(self._get_settings().telemetry_hz)
                    await cap.start_capture()
                    logged_regions = False
                    self._on_restart()
                    continue

                frames = cap.get_frames()
                cap.clear()  # keep memory flat
                if frames and not logged_regions:
                    logged_regions = True
                    self._log_regions(cap)
                for frame in frames:
                    sample = sample_from_frame(frame)
                    if sample is not None:
                        self._on_sample(sample)

                # Game exit. With a process handle it is noticed on the next poll (~0.1 s);
                # without one we fall back to listing processes once a second.
                if watcher is not None:
                    if watcher.exited():
                        return self._game_closed()
                    continue
                now = time.monotonic()
                if now - last_check < (_PROBE_FALLBACK_S if seen else _PROBE_WAITING_S):
                    continue
                last_check = now
                probe = await asyncio.to_thread(self._probe, self._get_settings().game_process)
                if probe.status is GameStatus.RUNNING:
                    if not seen:
                        self._on_message(f"Game detected ({probe.name})")
                        self._on_game_state(True)
                    seen, missing = True, 0
                    watcher = self._open_watcher(probe.pid) if probe.pid else None
                elif probe.status is GameStatus.ABSENT and seen:
                    missing += 1
                    if missing >= _GAME_MISSING_CHECKS:
                        return self._game_closed()
            return ExitReason.STOPPED
        finally:
            if watcher is not None:
                watcher.close()
            await cap.stop_capture()

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

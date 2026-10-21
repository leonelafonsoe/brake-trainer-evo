"""The game's own log: the per-cut events its shared memory does not publish, and its sector
splits, which are the only place its sector lines can be found (the shared memory has no sector
fields in this build).

Assetto Corsa EVO judges a track cut by the time it gains. It gives the driver a give-back window to
hand that time back and only reports the cut once the window has passed, as a HUD notification. That
notification is written to the log as::

    ... [gameface] [info] Adding notification UINotificationType_SessionPenalty

The shared memory carries only a one-shot "lap still valid" flag, which drops once per lap and so
cannot show a second cut; the notification arrives once per cut. Because the report lags the cut by
the give-back window, the engine attributes it to the sector the cut happened in, not the one the
report lands in (see ``Settings.cut_give_back_m``).

Every lap is scored in three sectors, and the end of each is written as::

    ... [gameplay] [info] Received split: isStart false, isEnd false, index 1

``index`` is the sector that just ended (2 is the start/finish line). The line itself is not named,
but the line's own timestamp says when the car crossed it, which is enough for the engine to place
it from the car's position then - the same history a late cut is attributed from.

The game buffers this log, so the app can read a notification several seconds after the game wrote
it, and several cuts can arrive in one read. Every line carries its own timestamp, so the reader
reports each event *with the time it happened*, and the engine attributes it from the car's position
then - not from wherever the car is when the line is finally seen.

Older builds wrote the excursion itself instead of a notification::

    ... [physics] [info] Limits: car <uuid> tyres out changed: 3 -> 4 with 2.62m inside

That line names the car, so the player's id is learned from the connection lines and only the
player's own excursions are reported.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / "Saved Games" / "ACE" / "Logs"
MIN_INSIDE_M = 2.0  # shorter excursions are tolerated by the game
PIT_TELEPORT_M = 10.0  # larger values are an artefact of being teleported to the pits

# One HUD notification per cut, written once the give-back window has passed.
_NOTIFY_RE = re.compile(r"Adding notification UINotificationType_SessionPenalty\b")
# The end of each of the game's three sectors: "Received split: ... index 0/1/2" (2 = the line).
_SPLIT_RE = re.compile(r"Received split: isStart (?:true|false), isEnd (?:true|false), index (\d+)")
# Every line starts with its own wall-clock time, in local time: ``[2026-10-16 22:11:06.027]``.
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]")
# Older builds: each change of the player's tyre-off count, with how far past the line they are.
_LIMITS_RE = re.compile(
    r"\[physics\] \[info\] Limits: car ([a-f0-9\-]+) tyres out changed: \d+ -> (\d+) "
    r"with ([\-\d.]+)m inside"
)
_CONNECT_RE = re.compile(
    r"(\d+) connected(?: \([^)]*\))? on car ([\w_]+), with new carId ([a-f0-9\-]+)"
)

REPORTED_CUT = "the game reported a cut"
REPORTED_TYRES_OUT = "the game's log reported all four tyres off the track"


@dataclass(frozen=True, slots=True)
class LogEvent:
    """Something the engine needs to hear about, taken from one line of the game's log."""

    cut: str = ""  # a cut the game reported, or ""
    split: int = -1  # the game's sector index that just ended, or -1


def line_time(line: str, fallback: float) -> float:
    """The wall-clock time the game wrote ``line``, as POSIX seconds.

    The game buffers its log, so a line can be read long after it was written; the line's own
    timestamp is the only reliable time for the event. Falls back to ``fallback`` if it is missing.
    """
    match = _TS_RE.match(line)
    if match is None:
        return fallback
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except ValueError:
        return fallback


def _norm(uuid: str) -> str:
    return uuid.replace("-", "").lower()


def _is_steam_id(pid: str) -> bool:
    return len(pid) == 17 and pid.startswith("7656")


@dataclass
class LogState:
    """What has been learned from the log so far: which car is the player's."""

    player_uuids: set[str] = field(default_factory=set)
    _seen_non_steam: str | None = None

    def clear(self) -> None:
        self.player_uuids.clear()
        self._seen_non_steam = None


def parse_line(line: str, state: LogState) -> LogEvent | None:
    """Feed one log line. Returns what it reports for the player's car, if anything."""
    if "connected" in line and "with new carId" in line:
        match = _CONNECT_RE.search(line)
        if match:
            pid, uuid = match.group(1), _norm(match.group(3))
            if _is_steam_id(pid):
                state.player_uuids.add(uuid)
            elif not state.player_uuids and state._seen_non_steam is None:
                # offline / unknown id: assume the first car that connects is the player's
                state._seen_non_steam = uuid
                state.player_uuids.add(uuid)
        return None
    if _NOTIFY_RE.search(line):
        return LogEvent(cut=REPORTED_CUT)
    match = _SPLIT_RE.search(line)
    if match:
        return LogEvent(split=int(match.group(1)))
    if "Limits: car" not in line or "tyres out changed" not in line:
        return None
    match = _LIMITS_RE.search(line)
    if not match:
        return None
    uuid, tyres_out, inside = _norm(match.group(1)), int(match.group(2)), float(match.group(3))
    if uuid not in state.player_uuids or tyres_out != 4:
        return None
    if MIN_INSIDE_M <= inside <= PIT_TELEPORT_M:
        return LogEvent(cut=REPORTED_TYRES_OUT)
    return None


def newest_log(directory: Path) -> Path | None:
    try:
        files = list(directory.glob("*.txt"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


class GameLogTail:
    """Follows the newest log file and reports the player's cuts and sector splits as they land.

    On a new file everything already in it is read first (to learn which car is the player's)
    without reporting, so old events are never replayed.
    """

    def __init__(
        self,
        directory: Path,
        on_cut: Callable[[str, float], None],
        on_message: Callable[[str], None] = lambda text: None,
        on_split: Callable[[int, float], None] = lambda index, at: None,
        poll_s: float = 0.25,
        rescan_s: float = 2.0,
    ) -> None:
        self._dir = directory
        self._on_cut = on_cut
        self._on_message = on_message
        self._on_split = on_split
        self._poll_s, self._rescan_s = poll_s, rescan_s
        self._state = LogState()
        self._path: Path | None = None
        self._offset = 0
        self._partial = b""
        self._live = False
        self._warned = False

    def _read_new(self) -> list[str]:
        """New complete lines since the last read (blocking, small)."""
        assert self._path is not None
        try:
            size = self._path.stat().st_size
            if size < self._offset:  # the file was replaced or truncated
                self._offset, self._partial = 0, b""
                self._state.clear()
                self._live = False
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
                self._offset = handle.tell()
        except OSError:
            return []
        chunks = (self._partial + data).split(b"\n")
        self._partial = chunks.pop()  # an unfinished last line waits for the next read
        return [c.decode("utf-8", errors="ignore") for c in chunks]

    def _switch_to(self, path: Path) -> None:
        self._path, self._offset, self._partial, self._live = path, 0, b"", False
        self._state.clear()
        self._on_message(f"Reading the game log for cuts and sector splits: {path}")

    async def run(self, stop: asyncio.Event) -> None:
        last_scan = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if self._path is None or now - last_scan >= self._rescan_s:
                last_scan = now
                latest = await asyncio.to_thread(newest_log, self._dir)
                if latest is None:
                    if not self._warned:
                        self._warned = True
                        self._on_message(f"No game log found in {self._dir} (set it in Settings)")
                elif latest != self._path:
                    self._warned = False
                    self._switch_to(latest)
            if self._path is not None:
                lines = await asyncio.to_thread(self._read_new)
                if lines:
                    # The game buffers its log: this can be a dozen lines or a whole minute of
                    # them. Each carries its own time, which is what the engine attributes from.
                    log.debug("gamelog: read %d new lines", len(lines))
                now = time.time()
                for line in lines:
                    event = parse_line(line, self._state)
                    if event is None or not self._live:
                        continue
                    at = line_time(line, now)
                    if event.cut:
                        self._on_cut(event.cut, at)
                    if event.split >= 0:
                        self._on_split(event.split, at)
                self._live = True  # everything that existed at the start has been read
            with contextlib.suppress(asyncio.TimeoutError):  # builtin TimeoutError only from 3.11
                await asyncio.wait_for(stop.wait(), timeout=self._poll_s)

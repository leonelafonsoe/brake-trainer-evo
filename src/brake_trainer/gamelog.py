"""The game's own log: the authoritative source for track-limit violations.

Assetto Corsa EVO writes a line every time the number of tyres off the track changes, with how far
inside the limit line they are. Following the analysis behind ``acevo-sdk``, the game invalidates a
lap when the player's car gets **all four tyres out with at least 2 m beyond the line**; shorter
excursions are tolerated, and a huge distance is an artefact of being teleported to the pits. The
shared-memory telemetry only has the tyre count, not that distance, so this reader follows the log.

Line formats (from the SDK, which parsed real logs)::

    ... [physics] [info] Limits: car <uuid> tyres out changed: 3 -> 4 with 2.62m inside
    ... <steam id> connected on car <model>, with new carId <uuid>
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / "Saved Games" / "ACE" / "Logs"
MIN_INSIDE_M = 2.0  # shorter excursions are tolerated by the game
PIT_TELEPORT_M = 10.0  # larger values are an artefact of being teleported to the pits

_LIMITS_RE = re.compile(
    r"\[physics\] \[info\] Limits: car ([a-f0-9\-]+) tyres out changed: \d+ -> (\d+) "
    r"with ([\-\d.]+)m inside"
)
_CONNECT_RE = re.compile(
    r"(\d+) connected(?: \(\d+\))? on car ([\w_]+), with new carId ([a-f0-9\-]+)"
)


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


def parse_line(line: str, state: LogState) -> bool:
    """Feed one log line. Returns True if it is a track-limit violation by the player's car."""
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
        return False
    if "Limits: car" not in line or "tyres out changed" not in line:
        return False
    match = _LIMITS_RE.search(line)
    if not match:
        return False
    uuid, tyres_out, inside = _norm(match.group(1)), int(match.group(2)), float(match.group(3))
    if uuid not in state.player_uuids or tyres_out != 4:
        return False
    return MIN_INSIDE_M <= inside <= PIT_TELEPORT_M


def newest_log(directory: Path) -> Path | None:
    try:
        files = list(directory.glob("*.txt"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


class GameLogTail:
    """Follows the newest log file and reports the player's track-limit violations as they happen.

    On a new file everything already in it is read first (to learn which car is the player's)
    without reporting, so old violations are never replayed.
    """

    def __init__(
        self,
        directory: Path,
        on_violation: Callable[[], None],
        on_message: Callable[[str], None] = lambda text: None,
        poll_s: float = 0.25,
        rescan_s: float = 2.0,
    ) -> None:
        self._dir = directory
        self._on_violation = on_violation
        self._on_message = on_message
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
        self._on_message(f"Reading the game log: {path}")

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
                for line in lines:
                    if parse_line(line, self._state) and self._live:
                        self._on_message("Game log: track-limit violation")
                        self._on_violation()
                self._live = True  # everything that existed at the start has been read
            with contextlib.suppress(asyncio.TimeoutError):  # builtin TimeoutError only from 3.11
                await asyncio.wait_for(stop.wait(), timeout=self._poll_s)

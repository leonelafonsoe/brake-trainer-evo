"""The game's own log: the per-cut events its shared memory does not publish, and its sector
splits, which are the only place its sector lines can be found (the shared memory has no sector
fields in this build).

Assetto Corsa EVO judges a track cut by the time it gains, and reports the cut as a HUD
notification::

    ... [gameface] [info] Adding notification UINotificationType_SessionPenalty

The shared memory carries only a one-shot "lap still valid" flag, which drops once per lap and so
cannot show a second cut; the notification arrives once per cut. The notification is written where
the game judged the cut, so the engine attributes it from the car's position at the line's own time,
not from wherever the car is when the buffered log is read.

Every lap is scored in three sectors, and the end of each is written as::

    ... [gameplay] [info] Received split: isStart false, isEnd false, index 1

``index`` is the sector that just ended (2 is the start/finish line). The line itself is not named,
but the line's own timestamp says when the car crossed it, which is enough for the engine to place
it from the car's position then - the same history a late cut is attributed from.

The game buffers this log, so the app can read a notification several seconds after the game wrote
it, and several cuts can arrive in one read. Every line carries its own timestamp, so the reader
reports each event *with the time it happened*, and the engine attributes it from the car's position
then - not from wherever the car is when the line is finally seen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / "Saved Games" / "ACE" / "Logs"
_FINGERPRINT_BYTES = 64  # bytes kept from before the read offset to spot an in-place rewrite

# One HUD notification per cut, written when the game judges it. The warning line that follows it
# (`false {PENALTY_CLEARED_KEY}` in the current build) carries the HUD text and penalty
# type, not whether a cut happened: matching only `{PENALTY_ADDED_KEY}` (as a penalty-state parser
# does) misses every cut this build reports.
_NOTIFY_RE = re.compile(r"Adding notification UINotificationType_SessionPenalty\b")
# The end of each of the game's three sectors: "Received split: ... index 0/1/2" (2 = the line).
_SPLIT_RE = re.compile(r"Received split: isStart (?:true|false), isEnd (?:true|false), index (\d+)")
# Every line starts with its own wall-clock time, in local time: ``[2026-10-16 22:11:06.027]``.
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]")

REPORTED_CUT = "the game reported a cut"


@dataclass(frozen=True, slots=True)
class LogEvent:
    """Something the engine needs to hear about, taken from one line of the game's log."""

    cut: str = ""  # a cut the game reported, or ""
    split: int = -1  # the game's sector index that just ended, or -1


def line_time(line: str) -> float | None:
    """The wall-clock time the game wrote ``line``, as POSIX seconds, or None if it has none.

    The game buffers its log, so a line can be read long after it was written; the line's own
    timestamp is the only reliable time for the event. A line without one cannot be attributed,
    so the caller skips it rather than guessing (the read time can be minutes late).
    """
    match = _TS_RE.match(line)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except ValueError:
        return None


def parse_line(line: str) -> LogEvent | None:
    """Read one log line. Returns the cut or split it reports, if any."""
    if _NOTIFY_RE.search(line):
        return LogEvent(cut=REPORTED_CUT)
    match = _SPLIT_RE.search(line)
    if match:
        return LogEvent(split=int(match.group(1)))
    return None


def newest_log(directory: Path) -> Path | None:
    try:
        files = list(directory.glob("*.txt"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


class GameLogTail:
    """Follows the newest log file and reports its cuts and sector splits as they land.

    A file that already has content when it is first seen is skipped: events written before the app
    started are history and must not be replayed.
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
        self._path: Path | None = None
        self._offset = 0
        self._partial = b""
        self._live = False
        self._warned = False
        self._undated_warned = False
        self._file_id: tuple[int, int] | None = None  # (st_dev, st_ino)
        self._mtime_ns = 0
        self._fingerprint = b""  # the bytes just before the offset, to spot an in-place rewrite

    def _reset_file(self, stat: os.stat_result) -> None:
        """Start this file from the top: it is new, or it was rewritten under us."""
        self._offset, self._partial = 0, b""
        self._live = False
        self._undated_warned = False
        self._file_id = (stat.st_dev, stat.st_ino)
        self._mtime_ns = stat.st_mtime_ns
        self._fingerprint = b""

    def _prefix_changed(self) -> bool:
        """Whether the bytes before the offset are not the ones we last read."""
        if not self._fingerprint:
            return False
        assert self._path is not None
        start = self._offset - len(self._fingerprint)
        try:
            with self._path.open("rb") as handle:
                handle.seek(start)
                return handle.read(len(self._fingerprint)) != self._fingerprint
        except OSError:
            return False

    @staticmethod
    def _read_fingerprint(handle: Any, offset: int) -> bytes:
        start = max(0, offset - _FINGERPRINT_BYTES)
        handle.seek(start)
        return bytes(handle.read(offset - start))

    def _read_new(self) -> list[str]:
        """New complete lines since the last read (blocking, small)."""
        assert self._path is not None
        try:
            stat = self._path.stat()
        except OSError:
            return []
        # A replaced file can be *larger* than the old one, so size alone cannot tell us: the game
        # starts a new log on every run. The inode names the file; when it is unchanged but the
        # mtime moved, the bytes we already read say whether it was rewritten in place.
        replaced = (stat.st_dev, stat.st_ino) != self._file_id or stat.st_size < self._offset
        if not replaced and stat.st_mtime_ns != self._mtime_ns and self._prefix_changed():
            replaced = True
        if replaced:
            self._reset_file(stat)
        self._mtime_ns = stat.st_mtime_ns
        if not self._live:
            # Nothing written before the app started is reported. Skip straight to the end, however
            # large the existing log is; only events that arrive from now on matter.
            self._offset = stat.st_size
            self._partial = b""
            self._fingerprint = b""
            return []
        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
                self._offset = handle.tell()
                self._fingerprint = self._read_fingerprint(handle, self._offset)
        except OSError:
            return []
        chunks = (self._partial + data).split(b"\n")
        self._partial = chunks.pop()  # an unfinished last line waits for the next read
        return [c.decode("utf-8", errors="ignore") for c in chunks]

    def _switch_to(self, path: Path) -> None:
        self._path, self._offset, self._partial, self._live = path, 0, b"", False
        self._file_id, self._mtime_ns, self._fingerprint = None, 0, b""
        self._undated_warned = False
        self._on_message(f"Reading the game log for cuts and sector splits: {path}")

    def _warn_undated(self) -> None:
        if self._undated_warned:
            return
        self._undated_warned = True
        self._on_message("Ignoring game-log lines without a timestamp")

    async def _read_and_report(self) -> None:
        """Read whatever the current file has and report the events that are new."""
        assert self._path is not None
        lines = await asyncio.to_thread(self._read_new)
        if lines:
            # The game buffers its log: this can be a dozen lines or a whole minute of them. Each
            # carries its own time, which is what the engine attributes from.
            log.debug("gamelog: read %d new lines", len(lines))
        for line in lines:
            event = parse_line(line)
            if event is None or not self._live:
                continue
            at = line_time(line)
            if at is None:
                # Guessing with the read time would file a buffered event under the position the
                # car has now, minutes later. Say so once and drop it.
                self._warn_undated()
                log.warning("gamelog: no timestamp on a line, skipping it: %r", line[:120])
                continue
            if event.cut:
                self._on_cut(event.cut, at)
            if event.split >= 0:
                self._on_split(event.split, at)
        self._live = True  # everything that existed at the start has been read

    async def poll_once(self) -> None:
        """Scan for the newest log and read anything new.

        :meth:`run` uses this on its rescan interval. Tests call it directly, so a file change and
        its effect are one step apart instead of racing a sleep.
        """
        latest = await asyncio.to_thread(newest_log, self._dir)
        if latest is None:
            if not self._warned:
                self._warned = True
                self._on_message(f"No game log found in {self._dir} (set it in Settings)")
        elif latest != self._path:
            self._warned = False
            self._switch_to(latest)
        if self._path is not None:
            await self._read_and_report()

    async def run(self, stop: asyncio.Event) -> None:
        last_scan = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if self._path is None or now - last_scan >= self._rescan_s:
                last_scan = now
                await self.poll_once()
            elif self._path is not None:
                await self._read_and_report()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_s)


class GameLogSupervisor:
    """Keeps a :class:`GameLogTail` in step with the current settings.

    The tail used to be built once with a settings snapshot, so turning the game log off, pointing
    it at another folder, or enabling it at runtime needed an app restart. Poll the live settings
    instead: stop the tail when it is not wanted, start it when it is, and restart it when the
    folder changes.
    """

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        on_cut: Callable[[str, float], None],
        on_message: Callable[[str], None] = lambda text: None,
        on_split: Callable[[int, float], None] = lambda index, at: None,
        poll_s: float = 0.5,
    ) -> None:
        self._get_settings = get_settings
        self._on_cut = on_cut
        self._on_message = on_message
        self._on_split = on_split
        self._poll_s = poll_s

    def _wanted(self) -> Path | None:
        settings = self._get_settings()
        if not settings.use_game_log:
            return None
        return (
            Path(settings.game_log_dir).expanduser() if settings.game_log_dir else DEFAULT_LOG_DIR
        )

    def _start(self, directory: Path, stop: asyncio.Event) -> asyncio.Task[None]:
        tail = GameLogTail(directory, self._on_cut, self._on_message, on_split=self._on_split)
        return asyncio.create_task(tail.run(stop))

    async def _stop_tail(
        self, task: asyncio.Task[None] | None, stop: asyncio.Event | None, *, cancel: bool
    ) -> None:
        """Stop a tail and wait for it, so its exceptions are not lost in the event loop."""
        if task is None:
            return
        if cancel:
            task.cancel()
        elif stop is not None:
            stop.set()
        try:
            await task
        except asyncio.CancelledError:
            if cancel:
                return  # we cancelled it; the supervisor is not itself being cancelled here
            raise
        except Exception:
            log.exception("Game-log tail failed")

    async def run(self, stop: asyncio.Event) -> None:
        task: asyncio.Task[None] | None = None
        tail_stop: asyncio.Event | None = None
        current: Path | None = None
        try:
            while not stop.is_set():
                if task is not None and task.done():
                    # The tail ended on its own (an unexpected error): report it, then let the
                    # next pass start a fresh one rather than waiting forever on a dead task.
                    await self._stop_tail(task, tail_stop, cancel=True)
                    task = tail_stop = None
                    current = None
                wanted = self._wanted()
                if wanted != current:
                    await self._stop_tail(task, tail_stop, cancel=False)
                    task = tail_stop = None
                    current = wanted
                    if wanted is not None:
                        tail_stop = asyncio.Event()
                        task = self._start(wanted, tail_stop)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_s)
        finally:
            await self._stop_tail(task, tail_stop, cancel=True)

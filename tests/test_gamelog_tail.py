from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from brake_trainer import gamelog as gamelog_module
from brake_trainer.config import Settings
from brake_trainer.gamelog import (
    DEFAULT_LOG_DIR,
    GameLogSupervisor,
    GameLogTail,
)

from .gamelog_helpers import NOTIFICATION, SPLIT


async def _wait(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_tail_reports_only_new_cuts_and_follows_newer_logs(tmp_path: Path):
    old = tmp_path / "old.txt"
    old.write_text(NOTIFICATION + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(tmp_path, lambda reason, at: hits.append((reason, at)))
    await tail.poll_once()
    assert hits == []  # history is not replayed

    with old.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION[:30])  # a line written in two pieces
    await tail.poll_once()
    assert hits == []

    with old.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION[30:] + "\n")
    await tail.poll_once()
    assert len(hits) == 1
    # The time is the line's own, not when it was read: the game buffers this log.
    assert hits[0][1] == datetime(2026, 10, 16, 20, 41, 38, 703000).timestamp()

    new = tmp_path / "new.txt"  # the game was restarted
    new.write_text(NOTIFICATION + "\n", encoding="utf-8")
    os.utime(new, (time.time() + 5, time.time() + 5))
    await tail.poll_once()
    assert len(hits) == 1  # its first content is history too

    with new.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    await tail.poll_once()
    assert len(hits) == 2


async def test_tail_reports_the_sector_splits_it_reads(tmp_path: Path):
    log = tmp_path / "log.txt"
    log.write_text(NOTIFICATION + "\n", encoding="utf-8")
    splits: list[tuple[int, float]] = []
    tail = GameLogTail(
        tmp_path,
        lambda reason, at: None,
        on_split=lambda index, at: splits.append((index, at)),
    )
    await tail.poll_once()
    assert splits == []  # history is not replayed

    with log.open("a", encoding="utf-8") as fh:
        fh.write(SPLIT + "\n")
    await tail.poll_once()
    assert len(splits) == 1
    assert splits[0][0] == 1
    assert splits[0][1] == datetime(2026, 10, 16, 20, 41, 0, 0).timestamp()


async def test_run_reads_new_lines_and_stops_when_asked(tmp_path: Path):
    # poll_once() is the test seam; run() is what the worker actually uses. Keep the loop itself
    # covered, including the fast path that only reads and does not rescan the folder.
    log = tmp_path / "log.txt"
    log.write_text(NOTIFICATION + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(
        tmp_path, lambda reason, at: hits.append((reason, at)), poll_s=0.01, rescan_s=10.0
    )
    stop = asyncio.Event()
    task = asyncio.create_task(tail.run(stop))
    assert await _wait(lambda: tail._live)
    assert hits == []  # history is not replayed

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    assert await _wait(lambda: len(hits) == 1)
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_a_log_that_disappears_between_scans_is_ignored(tmp_path: Path):
    # The game can rotate or delete its log while the reader is between scans. That is a missed
    # read, not a crash.
    log = tmp_path / "log.txt"
    log.write_text(NOTIFICATION + "\n", encoding="utf-8")
    tail = GameLogTail(tmp_path, lambda reason, at: None)
    await tail.poll_once()

    log.unlink()
    await tail.poll_once()

    assert tail._path == log  # it keeps the path it knew; the next scan picks up a new file


async def test_tail_without_a_log_folder_just_says_so(tmp_path: Path):
    messages: list[str] = []
    tail = GameLogTail(
        tmp_path / "missing",
        lambda reason, at: None,
        messages.append,
    )
    await tail.poll_once()
    assert any("No game log found" in m for m in messages)


async def test_a_larger_replacement_file_is_read_from_the_top_not_the_old_offset(
    tmp_path: Path,
):
    # The game starts a new log on every run; it can be larger than the one before. The old code
    # only reset when the file was *smaller*, so it resumed at the previous offset and reported the
    # middle of the new log's history as if it had just happened.
    log = tmp_path / "log.txt"
    original = NOTIFICATION + "\n"
    log.write_text(original, encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(tmp_path, lambda reason, at: hits.append((reason, at)))
    await tail.poll_once()
    assert tail._live

    replacement = tmp_path / "next.txt"
    replacement.write_text(original + NOTIFICATION + "\n" + "x" * 200 + "\n", encoding="utf-8")
    os.replace(replacement, log)  # a new inode, larger than the old file
    await tail.poll_once()
    assert hits == []  # the new file's existing content is history too

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    await tail.poll_once()
    assert len(hits) == 1


async def test_a_large_stale_log_is_skipped_to_its_end(tmp_path: Path):
    # A stale log can be megabytes long. Nothing in it can be reported, so it is skipped as a whole
    # instead of being read and parsed line by line.
    log = tmp_path / "log.txt"
    log.write_text(NOTIFICATION + "\n" + "x" * 500 + "\n" + NOTIFICATION + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    tail = GameLogTail(tmp_path, lambda reason, at: hits.append((reason, at)))
    await tail.poll_once()
    assert tail._live
    assert tail._offset == log.stat().st_size  # the rest of the history was skipped
    assert hits == []

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    await tail.poll_once()
    assert len(hits) == 1


async def test_an_undated_event_is_skipped_and_warned_about_once(tmp_path: Path):
    # The line's own time is what places it. Without one, using the read time would file a buffered
    # event minutes late, so it is dropped - and the driver is told why, once.
    log = tmp_path / "log.txt"
    log.write_text(NOTIFICATION + "\n", encoding="utf-8")
    hits: list[tuple[str, float]] = []
    messages: list[str] = []
    tail = GameLogTail(tmp_path, lambda reason, at: hits.append((reason, at)), messages.append)
    await tail.poll_once()
    assert tail._live

    with log.open("a", encoding="utf-8") as fh:
        fh.write(
            "[gameface] [info] Adding notification UINotificationType_SessionPenalty\n"
            "[gameface] [info] Adding notification UINotificationType_SessionPenalty\n"
        )
    await tail.poll_once()
    assert hits == []
    assert messages.count("Ignoring game-log lines without a timestamp") == 1

    with log.open("a", encoding="utf-8") as fh:
        fh.write(NOTIFICATION + "\n")
    await tail.poll_once()
    assert len(hits) == 1


class FakeTail:
    """Stands in for the real tail: records its folder and when it was stopped."""

    created: list[FakeTail] = []

    def __init__(self, directory, on_cut, on_message, on_split=lambda index, at: None) -> None:
        self.directory = directory
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        FakeTail.created.append(self)

    async def run(self, stop: asyncio.Event) -> None:
        self.started.set()
        try:
            await stop.wait()
        finally:
            self.finished.set()


async def test_the_supervisor_follows_runtime_settings(tmp_path: Path, monkeypatch):
    FakeTail.created.clear()
    monkeypatch.setattr(gamelog_module, "GameLogTail", FakeTail)
    current = {"settings": Settings(use_game_log=False)}
    stop = asyncio.Event()
    supervisor = GameLogSupervisor(
        lambda: current["settings"], lambda reason, at: None, poll_s=0.01
    )
    task = asyncio.create_task(supervisor.run(stop))
    await asyncio.sleep(0.05)
    assert FakeTail.created == []  # disabled: no tail at all

    current["settings"] = replace(current["settings"], use_game_log=True)
    assert await _wait(lambda: len(FakeTail.created) == 1)
    first = FakeTail.created[0]
    assert first.directory == DEFAULT_LOG_DIR  # empty folder = the usual place

    current["settings"] = replace(current["settings"], game_log_dir=str(tmp_path))
    assert await _wait(lambda: len(FakeTail.created) == 2)
    assert first.finished.is_set()  # the old tail was stopped, not left running
    assert FakeTail.created[1].directory == tmp_path

    current["settings"] = replace(current["settings"], use_game_log=False)
    assert await _wait(lambda: FakeTail.created[1].finished.is_set())

    stop.set()
    await asyncio.wait_for(task, 2)


async def test_cancelling_the_supervisor_stops_its_tail(monkeypatch):
    FakeTail.created.clear()
    monkeypatch.setattr(gamelog_module, "GameLogTail", FakeTail)
    stop = asyncio.Event()
    supervisor = GameLogSupervisor(
        lambda: Settings(use_game_log=True), lambda reason, at: None, poll_s=0.01
    )
    task = asyncio.create_task(supervisor.run(stop))
    assert await _wait(lambda: len(FakeTail.created) == 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert FakeTail.created[0].finished.is_set()  # no tail outlives the worker's loop

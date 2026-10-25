"""Persistence of learned braking data: one JSON file per track + car."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .metadata import save_metadata
from .models import NewerDataError, TrackData

log = logging.getLogger(__name__)

QUARANTINE_DIR = "quarantine"


@dataclass(frozen=True, slots=True)
class StoreResult:
    """Outcome of a write, edit or delete.

    ``ok`` is False when the operation was refused or failed; ``changed`` is True only when the
    stored data actually changed, so callers can tell "nothing to do" from "the write failed".
    The result is truthy exactly when something changed, which keeps the old boolean call sites
    working.
    """

    ok: bool = True
    changed: bool = False
    detail: str = ""

    def __bool__(self) -> bool:
        return self.changed


class LoadStatus(StrEnum):
    """Why a learned-data file could or could not be used."""

    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"
    NEWER = "newer"
    LAYOUT_MISMATCH = "layout_mismatch"


@dataclass(frozen=True, slots=True)
class LoadResult:
    status: LoadStatus
    data: TrackData | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class StorageIssue:
    """A file this build could not use, and what happened to it."""

    path: Path
    status: LoadStatus
    detail: str
    quarantine_path: Path | None = None

    @property
    def blocked(self) -> bool:
        """True when the file could not be moved and must not be overwritten."""
        return self.quarantine_path is None


@dataclass(frozen=True, slots=True)
class DeleteEntry:
    """Forget everything learned for a track + car."""

    track: str
    car: str


@dataclass(frozen=True, slots=True)
class DeleteSector:
    """Forget all stored runs of one sector."""

    track: str
    car: str
    sector: int


@dataclass(frozen=True, slots=True)
class DeleteRun:
    """Forget one stored run of a sector.

    ``time`` alone cannot name a run: two runs of one sector can have the same time (different
    laps, same pace) and the fastest list changes as you drive. ``onsets`` is the run's other
    content, so a delete names exactly the row the driver picked.
    """

    track: str
    car: str
    sector: int
    time: float
    onsets: tuple[float, ...]


DataEdit = DeleteEntry | DeleteSector | DeleteRun


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "unknown"


def _identity(track: str, car: str) -> str:
    """A collision-free key for one track + car, independent of the display names' punctuation.

    The slug is only for a readable filename. Two names that slug the same (``Car A`` and
    ``Car/A``) still have different identities, which the short hash in the filename records.
    """
    return f"{track}\0{car}"


class TrackStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._blocked: set[Path] = set()
        self._issues: dict[Path, StorageIssue] = {}
        self._pending_issues: list[StorageIssue] = []
        # The worker saves and the settings window lists entries; the issue/blocked maps are the
        # only state both touch, so they are the only state that needs a lock.
        self._lock = threading.Lock()

    def _legacy_path(self, track: str, car: str) -> Path:
        """The name written before collision handling; still the first choice when it is ours."""
        return self.directory / f"{_slug(track)}__{_slug(car)}.json"

    def _hashed_path(self, track: str, car: str) -> Path:
        digest = hashlib.sha256(_identity(track, car).encode("utf-8")).hexdigest()[:12]
        return self.directory / f"{_slug(track)}__{_slug(car)}--{digest}.json"

    @staticmethod
    def _stored_names(path: Path) -> tuple[str, str] | None:
        """The track and car recorded in a file, or None if it cannot be read that far.

        This is deliberately cheap and side-effect free: it decides which filename belongs to
        which identity before a save, so an unreadable file is never overwritten just because its
        name happens to match.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return str(raw["track"]), str(raw["car"])
        except (OSError, TypeError, ValueError, KeyError):
            return None

    def _target(self, track: str, car: str) -> Path:
        """Where this identity is stored: its hashed name if it has one, else the legacy name.

        A legacy file is ours only when the names inside it match. If it belongs to another
        identity (a slug collision) or cannot be read, this identity uses the hashed name: two
        different track/car pairs must never share a file, and an unreadable file must never be
        overwritten.
        """
        hashed = self._hashed_path(track, car)
        if hashed.exists():
            return hashed
        legacy = self._legacy_path(track, car)
        if not legacy.exists() or self._stored_names(legacy) == (track, car):
            return legacy
        return hashed

    def _candidates(self, track: str, car: str) -> list[Path]:
        """The files that may hold this identity, in the order to read them."""
        hashed = self._hashed_path(track, car)
        legacy = self._legacy_path(track, car)
        paths: list[Path] = []
        if hashed.exists():
            paths.append(hashed)
        # A missing legacy name is a fresh entry. An existing one belongs to us only when its
        # recorded names match (or it is unreadable, so reading it will quarantine/block it).
        names = self._stored_names(legacy) if legacy.exists() else (track, car)
        if names is None or names == (track, car):
            paths.append(legacy)
        return paths

    @property
    def quarantine_directory(self) -> Path:
        return self.directory / QUARANTINE_DIR

    def issues(self) -> list[StorageIssue]:
        """Every unsafe file seen this process, including ones already quarantined."""
        with self._lock:
            return [self._issues[path] for path in sorted(self._issues)]

    def take_issues(self) -> list[StorageIssue]:
        """New issues since the last call, for the engine to surface once."""
        with self._lock:
            pending, self._pending_issues = self._pending_issues, []
            return pending

    def _record(self, issue: StorageIssue) -> None:
        with self._lock:
            self._issues[issue.path] = issue
            self._pending_issues.append(issue)

    def _quarantine(self, path: Path, status: LoadStatus) -> Path | None:
        """Move an unsafe file aside, returning its new path or ``None`` if that failed."""
        try:
            folder = self.quarantine_directory
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            target = folder / f"{path.stem}.{status.value}-{stamp}{path.suffix}"
            counter = 1
            while target.exists():
                target = folder / f"{path.stem}.{status.value}-{stamp}-{counter}{path.suffix}"
                counter += 1
            os.replace(path, target)
            return target
        except OSError as exc:
            log.warning("Could not quarantine %s: %s", path, exc)
            return None

    def _unsafe(self, path: Path, status: LoadStatus, detail: str) -> LoadResult:
        """Archive an unusable file, or block it if it cannot be moved.

        A quarantined file is gone from the data folder, so the next save starts a fresh entry
        there. A blocked file stays put and is never overwritten by this process.
        """
        quarantine = self._quarantine(path, status)
        if quarantine is not None:
            log.warning(
                "Learned data %s could not be read (%s); moved to %s",
                path.name,
                detail,
                quarantine,
            )
            self._record(StorageIssue(path, status, detail, quarantine))
        else:
            with self._lock:
                self._blocked.add(path)
            log.error(
                "Learned data %s could not be read (%s) and could not be moved; "
                "it will not be overwritten",
                path.name,
                detail,
            )
            self._record(StorageIssue(path, status, detail))
        return LoadResult(status, detail=detail)

    def _read(self, path: Path) -> LoadResult:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LoadResult(LoadStatus.MISSING)  # no data yet, or the entry was just deleted
        except OSError as exc:
            return self._unsafe(path, LoadStatus.CORRUPT, f"could not read: {exc}")
        except (TypeError, ValueError) as exc:
            return self._unsafe(path, LoadStatus.CORRUPT, f"invalid JSON: {exc}")

        try:
            data = TrackData.from_dict(raw)
        except NewerDataError as exc:
            return self._unsafe(path, LoadStatus.NEWER, str(exc))
        except (KeyError, TypeError, ValueError) as exc:
            return self._unsafe(path, LoadStatus.CORRUPT, f"invalid data: {exc}")
        return LoadResult(LoadStatus.OK, data)

    def load(self, track: str, car: str, n_sectors: int) -> TrackData:
        """Stored data for this combination, or an empty set if none (or a different layout).

        An unusable file is moved to ``data/quarantine/`` and a fresh entry starts. If it cannot
        be moved, the path is blocked for the rest of the process and saves to it are refused.
        """
        for path in self._candidates(track, car):
            result = self._read(path)
            if result.status is LoadStatus.MISSING:
                continue
            if result.status is not LoadStatus.OK or result.data is None:
                continue  # unsafe; try any duplicate, or report the empty entry
            if result.data.n_sectors != n_sectors:
                detail = f"{result.data.n_sectors} sectors, expected {n_sectors}"
                self._unsafe(path, LoadStatus.LAYOUT_MISMATCH, detail)
                continue
            return result.data
        return TrackData.empty(track, car, n_sectors)

    def save(self, data: TrackData) -> StoreResult:
        """Write one entry.

        ``ok`` is False if the write failed or the path is blocked, with the reason in ``detail``;
        the temporary file is removed and the previous entry is left untouched.
        """
        path = self._target(data.track, data.car)
        with self._lock:
            blocked = path in self._blocked
        if blocked:
            detail = "the file could not be read and must not be overwritten"
            log.error("Refusing to overwrite unreadable learned data %s", path.name)
            return StoreResult(ok=False, detail=detail)
        tmp = path.with_suffix(".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {**save_metadata(), **data.to_dict()}
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload))
                handle.flush()
                os.fsync(handle.fileno())  # durable before the replace, not just in the cache
            os.replace(tmp, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            log.warning("Could not save learned data: %s", exc)
            return StoreResult(ok=False, detail=str(exc))
        return StoreResult(changed=True)

    def entries(self) -> list[TrackData]:
        if not self.directory.exists():
            return []
        found = (self._read(p) for p in sorted(self.directory.glob("*.json")))
        return [r.data for r in found if r.status is LoadStatus.OK and r.data is not None]

    def find_reference(
        self, track: str, car: str, n_sectors: int, preferred: str = ""
    ) -> TrackData | None:
        """Another car's data on the same track, to borrow braking points from."""
        candidates = [
            d
            for d in self.entries()
            if d.track == track and d.car != car and d.n_sectors == n_sectors and d.total_runs()
        ]
        if not candidates:
            return None
        if preferred:
            named = [d for d in candidates if preferred.lower() in d.car.lower()]
            if named:
                return named[0]
            log.info("No stored data for a car matching %r on %s", preferred, track)
        return max(
            candidates, key=lambda d: (d.sectors_with_data(), d.total_runs(), -d.best_total())
        )

    def share_lines(self, data: TrackData) -> str:
        """Take the sector lines another entry on this track learned, if this one has none.

        The game's own lines are the track's, not the car's, so one car's entry teaches the
        others here and no car has to wait for the game's log twice. An entry with runs keeps
        the lines it was timed on, since moving those would re-file every stored run. Returns
        the car the lines came from, or "" if nothing was taken.
        """
        if data.boundaries is not None or data.total_runs():
            return ""
        for other in self.entries():
            if (
                other.track == data.track
                and other.car != data.car
                and other.n_sectors == data.n_sectors
                and other.boundaries
            ):
                data.boundaries = list(other.boundaries)
                return other.car if self.save(data) else ""
        return ""

    def apply(self, edit: DataEdit) -> StoreResult:
        """Apply an edit to the stored files.

        A refused or failed write has ``ok=False`` and leaves the file untouched; "nothing to
        delete" is ``ok=True`` with ``changed=False``.
        """
        if isinstance(edit, DeleteEntry):
            return self.delete(edit.track, edit.car)
        result = self._read(self._target(edit.track, edit.car))
        data = result.data
        if result.status is LoadStatus.MISSING:
            return StoreResult()  # nothing stored: a successful no-op
        if result.status is not LoadStatus.OK or data is None:
            # A file that could not be read is a refusal, not "nothing to delete": the caller must
            # report it instead of pretending the edit succeeded.
            return StoreResult(
                ok=False, detail=result.detail or "the stored file could not be read"
            )
        if not 0 <= edit.sector < data.n_sectors:
            return StoreResult(ok=False, detail="the stored file has no such sector")
        runs = data.sectors[edit.sector]
        if isinstance(edit, DeleteSector):
            if not runs:
                return StoreResult()
            data.sectors[edit.sector] = []
        else:
            # The time alone is not an identity: two runs can share it. The onsets name the row
            # the driver picked; a request that no longer matches is a no-op, not a wrong delete.
            index = next(
                (
                    i
                    for i, run in enumerate(runs)
                    if abs(run.t - edit.time) < 1e-6 and tuple(run.onsets) == edit.onsets
                ),
                None,
            )
            if index is None:
                return StoreResult()
            del runs[index]
        return self.save(data)

    def delete(self, track: str, car: str) -> StoreResult:
        paths = [path for path in self._candidates(track, car) if path.exists()]
        if not paths:
            with self._lock:
                for path in self._candidates(track, car):
                    self._blocked.discard(path)
                    self._issues.pop(path, None)
            return StoreResult()
        changed = False
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("Could not delete learned data %s: %s", path.name, exc)
                return StoreResult(ok=False, detail=str(exc))
            else:
                changed = True
            with self._lock:
                self._blocked.discard(path)
                self._issues.pop(path, None)
        return StoreResult(changed=changed)

    def clear(self) -> int:
        return sum(1 for d in self.entries() if self.delete(d.track, d.car).changed)

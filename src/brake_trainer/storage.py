"""Persistence of learned braking data: one JSON file per track + car."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .metadata import save_metadata
from .models import TrackData

log = logging.getLogger(__name__)


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
    """Forget one stored run of a sector (found by its time, as lists change as you drive)."""

    track: str
    car: str
    sector: int
    time: float


DataEdit = DeleteEntry | DeleteSector | DeleteRun


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "unknown"


class TrackStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, track: str, car: str) -> Path:
        return self.directory / f"{_slug(track)}__{_slug(car)}.json"

    @staticmethod
    def _read(path: Path) -> TrackData | None:
        try:
            return TrackData.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None  # no data yet: never driven, or the entry was just deleted
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.debug("Skipping unreadable data file %s (%s)", path.name, exc)
            return None

    def load(self, track: str, car: str, n_sectors: int) -> TrackData:
        """Stored data for this combination, or an empty set if none (or a different layout)."""
        data = self._read(self._path(track, car))
        if data is None or data.n_sectors != n_sectors:
            return TrackData.empty(track, car, n_sectors)
        return data

    def save(self, data: TrackData) -> None:
        path = self._path(data.track, data.car)
        tmp = path.with_suffix(".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {**save_metadata(), **data.to_dict()}
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("Could not save learned data: %s", exc)

    def entries(self) -> list[TrackData]:
        if not self.directory.exists():
            return []
        found = (self._read(p) for p in sorted(self.directory.glob("*.json")))
        return [d for d in found if d is not None]

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
                self.save(data)
                return other.car
        return ""

    def apply(self, edit: DataEdit) -> bool:
        """Apply an edit to the stored files. Returns False if there was nothing to change."""
        if isinstance(edit, DeleteEntry):
            return self.delete(edit.track, edit.car)
        data = self._read(self._path(edit.track, edit.car))
        if data is None or not 0 <= edit.sector < data.n_sectors:
            return False
        runs = data.sectors[edit.sector]
        if isinstance(edit, DeleteSector):
            if not runs:
                return False
            data.sectors[edit.sector] = []
        else:
            index = next((i for i, r in enumerate(runs) if abs(r.t - edit.time) < 1e-6), None)
            if index is None:
                return False
            del runs[index]
        self.save(data)
        return True

    def delete(self, track: str, car: str) -> bool:
        try:
            self._path(track, car).unlink()
            return True
        except OSError:
            return False

    def clear(self) -> int:
        return sum(self.delete(d.track, d.car) for d in self.entries())

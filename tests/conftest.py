from __future__ import annotations

from collections.abc import Callable

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import CueKind, Sample
from brake_trainer.storage import TrackStore

DT = 1 / 30
LENGTH = 5000.0


class Driver:
    """Drives an engine around a synthetic track with braking zones at given positions."""

    def __init__(self, engine: BrakeEngine, track: str = "Monza", car: str = "Car A") -> None:
        self.engine, self.track, self.car = engine, track, car
        self.t = 0.0

    def feed(
        self,
        pos: float,
        speed: float,
        brake: float,
        pit: bool = False,
        valid: bool = True,
        tyres_out: int = 0,
    ) -> None:
        self.t += DT
        self.engine.update(
            Sample(
                self.track, self.car, LENGTH, pos % 1.0, brake, speed, pit, self.t, valid, tyres_out
            )
        )

    def lap(
        self,
        corners: list[float],
        speed_fn: Callable[[float], float] = lambda p: 200.0,
        start: float = 0.0001,
        stop: float = 1.0001,
        jitter: float = 0.0,
        invalid_from: float | None = None,
        off_track: tuple[float, float] | None = None,
    ) -> float:
        p = start
        while p < stop:
            speed, brake = speed_fn(p % 1.0), 0.0
            for c in corners:
                d = ((p % 1.0) - c - jitter) * LENGTH
                if 0 <= d < 120:
                    brake, speed = 0.8, min(speed, 200 - d * 0.9)
            valid = invalid_from is None or p < invalid_from
            out = 4 if off_track and off_track[0] <= p < off_track[1] else 0
            self.feed(p, speed, brake, valid=valid, tyres_out=out)
            p += speed / 3.6 * DT / LENGTH
        return p


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test session (offscreen, no display needed)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def store(tmp_path):
    return TrackStore(tmp_path / "data")


@pytest.fixture
def cues():
    return []


@pytest.fixture
def make_engine(store, cues):
    def factory(**overrides) -> BrakeEngine:
        return BrakeEngine(
            Settings(**{"warmup_laps": 0, **overrides}),
            store,
            on_cue=lambda kind: cues.append(kind),
        )

    return factory


__all__ = ["CueKind", "Driver"]

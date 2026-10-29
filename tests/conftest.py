from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import CueKind, Sample
from brake_trainer.storage import TrackStore

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

DT = 1 / 30
LENGTH = 5000.0


class Driver:
    """Drives an engine around a synthetic track with braking zones at given positions."""

    def __init__(
        self,
        engine: BrakeEngine,
        track: str = "Monza",
        car: str = "Car A",
        length: float = LENGTH,
    ) -> None:
        self.engine, self.track, self.car = engine, track, car
        self.length = length
        self.t = 0.0

    def feed(
        self,
        pos: float,
        speed: float,
        brake: float,
        pit: bool = False,
        valid: bool = True,
        cut_gained_ms: int = 0,
        cut_deadline_m: int = 0,
    ) -> None:
        self.t += DT
        self.engine.update(
            Sample(
                track=self.track,
                car=self.car,
                length_m=self.length,
                pos=pos % 1.0,
                brake=brake,
                speed_kmh=speed,
                in_pit=pit,
                t=self.t,
                lap_valid=valid,
                cut_gained_ms=cut_gained_ms,
                cut_deadline_m=cut_deadline_m,
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
        cut: tuple[float, float] | None = None,
    ) -> float:
        p = start
        while p < stop:
            speed, brake = speed_fn(p % 1.0), 0.0
            for c in corners:
                d = ((p % 1.0) - c - jitter) * self.length
                if 0 <= d < 120:
                    brake, speed = 0.8, min(speed, 200 - d * 0.9)
            valid = invalid_from is None or p < invalid_from
            down = bool(cut and cut[0] <= p < cut[1])
            self.feed(
                p,
                speed,
                brake,
                valid=valid,
                cut_gained_ms=250 if down else 0,
                cut_deadline_m=120 if down else 0,
            )
            p += speed / 3.6 * DT / self.length
        return p

    def split(self, index: int, at: float | None = None) -> None:
        """The game's log reported the end of sector ``index``.

        ``at`` is when the game wrote it; the default, the car's current time, is what a log read
        with no lag looks like. A buffered log is read later, so its lines carry an older time.
        """
        self.engine.report_split(index, self.t if at is None else at)


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """One QApplication for the whole test session (offscreen, no display needed)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def close_qt_windows(qapp: QApplication) -> Iterator[None]:
    """Destroy any top-level window a test made before the interpreter tears Qt down.

    Modules that build widgets mark themselves with
    ``pytestmark = pytest.mark.usefixtures("close_qt_windows")``. Leaving top-level widgets for
    the GC mixes Python and C++ destruction order; on exit that can double-free the QApplication.
    """
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def store(tmp_path: Path) -> TrackStore:
    return TrackStore(tmp_path / "data")


@pytest.fixture
def cues() -> list[CueKind]:
    return []


@pytest.fixture
def make_engine(store: TrackStore, cues: list[CueKind]) -> Callable[..., BrakeEngine]:
    def factory(**overrides: Any) -> BrakeEngine:
        # use_game_log off keeps the tests off the game's log: without a split in sight the engine
        # would spend the first laps waiting for the game's sector lines before counting anything.
        return BrakeEngine(
            Settings(**{"warmup_laps": 0, "use_game_log": False, **overrides}),
            store,
            on_cue=lambda kind: cues.append(kind),
        )

    return factory


__all__ = ["CueKind", "Driver"]

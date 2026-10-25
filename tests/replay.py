"""Replay telemetry frames and game-log lines through the real engine.

This is a test-support module, not a second engine: it builds the same :class:`Sample` values the
telemetry adapter produces and feeds the game's own log lines at the time the game wrote them. Use
it to reproduce attribution bugs from a small, anonymized trace instead of the game.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from brake_trainer.engine import BrakeEngine
from brake_trainer.gamelog import LogState, line_time, parse_line
from brake_trainer.models import Sample

DEFAULT_DT = 1 / 30
DEFAULT_LENGTH_M = 5000.0


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    """One telemetry frame, optionally followed by a game-log line at the same moment."""

    pos: float
    speed_kmh: float = 200.0
    brake: float = 0.0
    in_pit: bool = False
    lap_valid: bool = True
    cut_gained_ms: int = 0
    cut_deadline_m: int = 0
    log_line: str = ""


def line_at(payload: str, at: float) -> str:
    """A game-log line with the same ``[YYYY-MM-DD HH:MM:SS.mmm]`` prefix the game uses."""
    stamp = datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return f"[{stamp}] {payload}"


class Replay:
    """Feed timestamped frames, and any log lines attached to them, to one engine."""

    def __init__(
        self,
        engine: BrakeEngine,
        *,
        track: str = "Monza",
        car: str = "Car A",
        length_m: float = DEFAULT_LENGTH_M,
        dt: float = DEFAULT_DT,
    ) -> None:
        self.engine = engine
        self.track = track
        self.car = car
        self.length_m = length_m
        self.dt = dt
        self.t = 0.0
        self._log = LogState()

    def feed(self, frame: ReplayFrame) -> None:
        self.t += self.dt
        self.engine.update(
            Sample(
                track=self.track,
                car=self.car,
                length_m=self.length_m,
                pos=frame.pos % 1.0,
                brake=frame.brake,
                speed_kmh=frame.speed_kmh,
                in_pit=frame.in_pit,
                t=self.t,
                lap_valid=frame.lap_valid,
                cut_gained_ms=frame.cut_gained_ms,
                cut_deadline_m=frame.cut_deadline_m,
            )
        )
        if not frame.log_line:
            return
        event = parse_line(frame.log_line, self._log)
        if event is None:
            return
        # The line's own timestamp is what the engine attributes from; the replay time is only a
        # fallback for a malformed line, and the engine will ignore an undated event in practice.
        at = line_time(frame.log_line)
        if at is None:
            return
        if event.cut:
            self.engine.report_infraction(event.cut, at)
        if event.split >= 0:
            self.engine.report_split(event.split, at)

    def run(self, frames: list[ReplayFrame]) -> None:
        for frame in frames:
            self.feed(frame)

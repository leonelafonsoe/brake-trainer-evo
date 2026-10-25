"""The recent car samples, and the position/time lookups built on them.

The game buffers its log, so a line can be read long after it was written. Placing a cut or a
sector line therefore means asking where the car was at the line's own timestamp, not where it is
now. This module keeps a bounded history of samples and answers that question by interpolating
between the two samples around the time, with explicit rules for the cases where interpolating
would invent a position the car never had: a reset, a teleport, or a start/finish wrap.

Keeping the rules here, rather than spread over the engine, is what makes them testable on their
own and keeps the live sector transition and the buffered log event using the same arithmetic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# A position change this large in one frame is a reset or a teleport, not driving: the pass in
# progress restarts there, and an event inside that frame is placed at the earlier sample.
JUMP_LAP = 0.05
MAX_POS = 0.99999


def clamp_pos(pos: float) -> float:
    """A lap position inside the range the engine works in (1.0 is the next lap's 0.0)."""
    return min(max(pos, 0.0), MAX_POS)


def wrap_delta(delta: float) -> float:
    """The signed, wrap-safe change between two lap positions."""
    return ((delta + 0.5) % 1.0) - 0.5


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    """One sampled car state, kept so a game-log event can be placed at its own time."""

    t: float
    pos: float
    speed_kmh: float
    in_pit: bool
    lap: int


@dataclass(frozen=True, slots=True)
class CarAt:
    """The car at an arbitrary time, interpolated between two samples."""

    t: float
    pos: float
    speed_kmh: float
    in_pit: bool
    lap: int


class PositionTimeline:
    """A bounded sample history and the position/time lookups built on it."""

    def __init__(self, keep_s: float) -> None:
        self._keep_s = keep_s
        self._points: deque[HistoryPoint] = deque()

    @property
    def last(self) -> HistoryPoint | None:
        """The newest sample, or None before the first one."""
        return self._points[-1] if self._points else None

    def clear(self) -> None:
        self._points.clear()

    def append(self, point: HistoryPoint) -> None:
        """Keep ``point`` and drop the samples older than the window."""
        self._points.append(
            HistoryPoint(point.t, clamp_pos(point.pos), point.speed_kmh, point.in_pit, point.lap)
        )
        cutoff = point.t - self._keep_s
        while self._points and self._points[0].t < cutoff:
            self._points.popleft()

    def at(self, at: float, latest: CarAt | None = None) -> CarAt | None:
        """The car at ``at``, interpolated between the samples around it.

        ``latest`` is the car as the engine knows it now. It is used when ``at`` is at or after the
        newest sample: the current state is more accurate than the history, and the newest sample
        may carry the lap number from before the line it just crossed.

        A pair whose samples both carry the old lap number but whose positions wrap the line is not
        interpolated across: the position would be in the new lap while the label stayed on the old
        one. The earlier sample is the safe choice there too, as it is for a pair spanning a reset
        or teleport: interpolating across one would invent a position the car never had. A pair one
        lap number apart is the frame just after the line instead: the first sample after the
        crossing still carries the old number, so the line was crossed on it and every time between
        the two belongs to the new lap. Those are interpolated as usual and labelled with the later
        sample's lap.

        ``in_pit`` is a discrete state, not a quantity: it is taken from the earlier sample and
        deliberately not interpolated, since the car is either in the pit lane or it is not.

        ``None`` when ``at`` is older than the kept history: guessing from the current position
        would drop the wrong sector, which is worse than saying nothing.
        """
        if latest is not None and at >= latest.t:
            return latest
        before: HistoryPoint | None = None
        after: HistoryPoint | None = None
        for point in reversed(self._points):
            if point.t <= at:
                before = point
                break
            after = point
        if before is None:
            return None
        if after is None:
            return _car_at(before, before.lap)
        new_lap = after.lap == before.lap + 1
        if after.lap != before.lap and not new_lap:
            # No pair on one lap to interpolate across: the earlier sample is the safe choice.
            return _car_at(before, before.lap)
        # One lap apart means the line was crossed on the earlier sample: everything between them
        # belongs to the new lap, so that is the label even when falling back to the earlier sample.
        lap = after.lap if new_lap else before.lap
        span = after.t - before.t
        if span <= 0.0:
            return _car_at(before, lap)
        share = (at - before.t) / span
        delta = wrap_delta(after.pos - before.pos)
        if abs(delta) > JUMP_LAP or (new_lap and delta < 0.0):
            # A reset or teleport between the samples - or, on a new lap, positions that do not run
            # forwards - means interpolating would invent a position the car never had, so the
            # earlier sample is where the event happened.
            return _car_at(before, lap)
        moved = before.pos + delta * share
        if moved >= 1.0 or moved <= 0.0:
            # The pair wraps the start/finish line inside one lap number, forwards or backwards:
            # interpolating would put the position in the next lap under this lap's label.
            return _car_at(before, lap)
        speed = before.speed_kmh + (after.speed_kmh - before.speed_kmh) * share
        return CarAt(at, clamp_pos(moved % 1.0), speed, before.in_pit, lap)

    def crossing(self, lap: int, line: float) -> float | None:
        """When the car crossed ``line`` during ``lap``, interpolated between two samples.

        ``line`` is a lap fraction: 0.0 starts the lap and 1.0 ends it (and starts the next one).
        A pair whose positions jump more than :data:`JUMP_LAP` is a reset or a teleport, not
        driving: the car never passed through the line between those samples, so it is not a
        crossing. None when that crossing is no longer in the kept history: guessing would file a
        run under a time the car never drove.
        """
        if line <= 0.0:
            return self.lap_start(lap)
        if line >= 1.0:
            return self.lap_start(lap + 1)
        previous: HistoryPoint | None = None
        for point in self._points:
            if (
                point.lap == lap
                and previous is not None
                and previous.lap == lap
                and previous.pos < line <= point.pos
                and abs(wrap_delta(point.pos - previous.pos)) <= JUMP_LAP
            ):
                span = point.pos - previous.pos
                if span > 0.0:
                    return crossing_between(previous.t, previous.pos, point.t, point.pos, line)
                return point.t
            previous = point
        return None

    def lap_start(self, lap: int) -> float | None:
        """When the car crossed the line that starts ``lap``, from the samples around the wrap.

        The history records the lap a sample was taken in, so the sample that lands just after the
        line still carries the old number: the crossing is the wrap (a large drop in position) in
        the sample or two before the first one of ``lap``. None when the history now begins after
        it, so a lap whose start it no longer holds is not timed from a guess.
        """
        points = list(self._points)  # indexed a few times below; a deque indexes in O(n)
        first = next((i for i, point in enumerate(points) if point.lap == lap), None)
        if first is None:
            return None
        # The sample taken in the frame that wraps the line still carries the old lap number, so
        # the crossing can be one or two samples before the first one labelled with the new lap.
        for j in (first, first - 1, first - 2):
            if j < 1:
                continue
            high, low = points[j - 1], points[j]
            if high.pos > 0.5 and low.pos < 0.05:  # the start/finish line between these two
                span = (1.0 - high.pos) + low.pos
                if span > 0.0:
                    return crossing_between(high.t, high.pos, low.t, low.pos, 0.0)
        return None


def _car_at(point: HistoryPoint, lap: int) -> CarAt:
    return CarAt(point.t, point.pos, point.speed_kmh, point.in_pit, lap)


def crossing_between(
    t0: float | None, p0: float | None, t1: float, p1: float, line: float
) -> float:
    """When the car crossed ``line`` between two samples.

    ``line`` is 0.0 for the start/finish line, which the car crosses at the lap wrap (position
    drops from near 1 to near 0) rather than by passing ``line`` from below. Interpolating here
    removes the frame quantisation and the bias to the earlier sample; the residual is the
    interpolation error described in ``docs/GAME_DATA.md``.

    The caller must only pass a line that really lies between the samples: ``p0 < line <= p1``
    for an inner line, or ``p1 < p0`` for the start/finish line. When it does not - the samples
    show no crossing at all - there is no time to interpolate, and returning the current sample
    is the honest no-crossing fallback; clamping a share into ``[0, 1]`` would instead invent a
    crossing at a sample where the car was on the other side of the line.
    """
    if t0 is None or p0 is None or t1 <= t0:
        return t1
    if line <= 0.0:
        if p1 >= p0:  # no wrap between the samples: the start/finish line was not crossed
            return t1
        span = (1.0 - p0) + p1
        share = (1.0 - p0) / span if span > 0.0 else 1.0
    else:
        if not (p0 < line <= p1):  # the line is not between the samples
            return t1
        span = p1 - p0
        share = (line - p0) / span if span > 0.0 else 1.0
    return t0 + (t1 - t0) * min(max(share, 0.0), 1.0)

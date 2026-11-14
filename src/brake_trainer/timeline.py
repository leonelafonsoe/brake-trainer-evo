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


@dataclass(frozen=True, slots=True)
class _Segment:
    """The samples either side of a time, and whether the gap can be interpolated honestly.

    ``lap`` is the lap label for a time in the gap: the later sample's on the start/finish seam,
    the earlier one everywhere else. ``share`` is how far through the gap the requested time is.
    ``interpolate`` is false when the gap is empty, spans a reset or teleport, changes lap in a way
    that is not a start/finish crossing, or wraps the line; the earlier sample is the answer then.
    """

    before: HistoryPoint
    after: HistoryPoint | None
    lap: int
    share: float
    interpolate: bool


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
        """The car at ``at``; None when it is older than the kept history.

        ``latest`` is the car as the engine knows it now. It is used when ``at`` is at or after the
        newest sample: the current state is more accurate than the history, and the newest sample
        may carry the lap number from before the line it just crossed. Otherwise the gap around
        ``at`` comes from :meth:`_segment_at`, which owns the lap, reset and wrap rules.
        """
        if latest is not None and at >= latest.t:
            return latest
        segment = self._segment_at(at)
        if segment is None:
            return None
        if not segment.interpolate or segment.after is None:
            return _car_at(segment.before, segment.lap)
        after = segment.after
        delta = wrap_delta(after.pos - segment.before.pos)
        moved = _between(segment.before.pos, segment.before.pos + delta, segment.share)
        speed = _between(segment.before.speed_kmh, after.speed_kmh, segment.share)
        return CarAt(at, clamp_pos(moved % 1.0), speed, segment.before.in_pit, segment.lap)

    def _segment_at(self, at: float) -> _Segment | None:
        """Bracket ``at`` and decide whether interpolating across the gap is honest.

        The gap is bracketed by the last sample at or before ``at`` and the first after it:

        * no earlier sample: the time is older than the kept history, so the answer is None rather
          than a guess from the current position;
        * no later sample: the newest sample is the answer; extrapolating would invent a position;
        * a lap number one greater is the start/finish seam: the sample that crossed the line still
          carries the old number, so every time between the two belongs to the new lap and the gap
          is interpolated with that label;
        * any other lap change is a reset or teleport, and a position change larger than
          :data:`JUMP_LAP` is too: interpolating would invent a position the car never had, so the
          earlier sample is where the event happened;
        * a gap whose interpolation would cross 1.0 or 0.0 within one lap number is the line the
          wrong way round (or a backward reset): the earlier sample is the safe answer.

        ``in_pit`` is a discrete state, not a quantity: it comes from the earlier sample and is
        deliberately not interpolated.
        """
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
            return _Segment(before, None, before.lap, 0.0, False)
        new_lap = after.lap == before.lap + 1
        if after.lap != before.lap and not new_lap:
            return _Segment(before, None, before.lap, 0.0, False)
        lap = after.lap if new_lap else before.lap
        span = after.t - before.t
        if span <= 0.0:
            return _Segment(before, after, lap, 0.0, False)
        share = _share(before.t, after.t, at)
        delta = wrap_delta(after.pos - before.pos)
        if abs(delta) > JUMP_LAP or (new_lap and delta < 0.0):
            return _Segment(before, after, lap, share, False)
        moved = _between(before.pos, before.pos + delta, share)
        if moved >= 1.0 or moved <= 0.0:
            return _Segment(before, after, lap, share, False)
        return _Segment(before, after, lap, share, True)

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


def _share(start: float, end: float, value: float) -> float:
    """Where ``value`` lies between ``start`` and ``end`` (1.0 when the span is empty)."""
    span = end - start
    return (value - start) / span if span > 0.0 else 1.0


def _between(start: float, end: float, share: float) -> float:
    """The value ``share`` of the way from ``start`` to ``end``, clamped to the segment.

    This is the one linear model the live position (:meth:`PositionTimeline.at`) and a buffered
    log event (:func:`crossing_between`) both use, so the two cannot drift apart in their
    arithmetic.
    """
    return start + (end - start) * min(max(share, 0.0), 1.0)


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

    The share and the linear step are the same ones :meth:`PositionTimeline.at` uses, so a buffered
    line and a live position cannot drift apart in their arithmetic.
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
        share = _share(p0, p1, line)
    return _between(t0, t1, share)

"""Small reusable widgets and drawn icons."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..models import SectorStatus, group_sizes
from . import theme


def sector_rects(
    n: int,
    boundaries: Sequence[float],
    width: float,
    *,
    segment_gap: float = 2.0,
    group_gap: float = 8.0,
) -> list[tuple[float, float]]:
    """``(left, width)`` of each sector segment, with gaps centred on the true lines.

    The game's sectors are not equal thirds - at the Red Bull Ring the first ends at 26% of the
    lap and at Spa the second at 72% - so equal segments would draw a boundary where the car
    never crosses it. Each segment spans its sector's real share of the lap instead, and the gap
    to the next one is centred on the game's line, so the boundary sits where the car crosses it.
    Equal shares are the fallback while the lines are unknown or unusable.
    """
    if n <= 0:
        return []
    shares = _sector_shares(n, boundaries)
    edges = [0.0]
    for share in shares:
        edges.append(edges[-1] + share * width)
    group_ends: set[int] = set()
    total = 0
    for size in group_sizes(n):
        total += size
        group_ends.add(total)
    rects: list[tuple[float, float]] = []
    for i in range(n):
        before = 0.0 if i == 0 else (group_gap if i in group_ends else segment_gap) / 2.0
        after = 0.0 if i == n - 1 else (group_gap if i + 1 in group_ends else segment_gap) / 2.0
        left, right = edges[i] + before, edges[i + 1] - after
        rects.append((left, max(right - left, 0.0)))
    return rects


def _sector_shares(n: int, boundaries: Sequence[float]) -> list[float]:
    """Each sector's share of the lap, normalized; equal shares if the lines are unusable."""
    if n <= 0:
        return []
    usable = len(boundaries) == n + 1 and all(boundaries[i] < boundaries[i + 1] for i in range(n))
    if not usable:
        return [1.0 / n] * n
    span = boundaries[-1] - boundaries[0]
    return [(boundaries[i + 1] - boundaries[i]) / span for i in range(n)]


class BarWidget(QWidget):
    """A thin rounded progress bar (value 0..1) with a configurable colour."""

    def __init__(self, parent: QWidget | None = None, height: int = 10) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._value = 0.0
        self._color = QColor(theme.ACCENT)

    def set_value(self, value: float, color: str | None = None) -> None:
        value = min(max(value, 0.0), 1.0)
        new_color = QColor(color) if color else self._color
        if value != self._value or new_color != self._color:
            self._value, self._color = value, new_color
            self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
        painter.drawRoundedRect(rect, radius, radius)
        if self._value > 0:
            width = max(rect.width() * self._value, rect.height())
            painter.setBrush(QBrush(self._color))
            fill = QRectF(rect.x(), rect.y(), width, rect.height())
            painter.drawRoundedRect(fill, radius, radius)


STATUS_COLORS = theme.STATUS_COLORS


class SectorBar(QWidget):
    """F1-style sector indicator: three groups of segments, coloured by how each sector went.

    Grey = not driven yet, yellow = slower than your kept runs, green = among your fastest,
    purple = your fastest.
    """

    _SEGMENT_GAP = 2.0
    _GROUP_GAP = 8.0

    def __init__(self, parent: QWidget | None = None, height: int = 9) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._status: tuple[SectorStatus, ...] = ()
        self._current: int | None = None
        self._progress = 0.0
        self._boundaries: tuple[float, ...] = ()

    def set_state(
        self,
        status: tuple[SectorStatus, ...],
        current: int | None,
        progress: float,
        boundaries: Sequence[float] = (),
    ) -> None:
        bounds = tuple(boundaries)
        state = (status, current, round(progress, 2), bounds)
        if state != (self._status, self._current, round(self._progress, 2), self._boundaries):
            self._status, self._current = status, current
            self._progress, self._boundaries = progress, bounds
            self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        n = len(self._status)
        if n == 0:
            return
        rects = sector_rects(
            n,
            self._boundaries,
            self.width(),
            segment_gap=self._SEGMENT_GAP,
            group_gap=self._GROUP_GAP,
        )
        h = float(self.height())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, (left, seg_w) in enumerate(rects):
            rect = QRectF(left, 0, seg_w, h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(STATUS_COLORS[self._status[index]]))
            painter.drawRoundedRect(rect, h / 2.5, h / 2.5)
            if index == self._current:
                painter.setBrush(QColor(255, 255, 255, 110))
                fill = QRectF(left, 0, max(seg_w * self._progress, 0.0), h)
                painter.drawRoundedRect(fill, h / 2.5, h / 2.5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QColor(255, 255, 255, 230))
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), h / 2.5, h / 2.5)

"""Small reusable widgets and drawn icons."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..models import SectorStatus
from . import theme


def sector_rects(
    n: int,
    boundaries: Sequence[float],
    width: float,
) -> list[tuple[float, float]]:
    """``(left, width)`` of each sector segment, in lap order, meeting on the true lines.

    The game's sectors are not equal thirds - at the Red Bull Ring the first ends at 26% of the
    lap and at Spa the second at 72% - so equal segments would draw a boundary where the car
    never crosses it. Each segment spans its sector's real share of the lap instead, so the joint
    between two is the game's own line. They meet exactly: a gap would leave a dead zone where
    neither sector is shown, and on a 272 px bar the old 8 px gap was 2.9% of the lap - 170 m at
    Monza, enough for the braking point for the next corner to fall inside it. The bar draws a
    thin separator at the joint instead. Equal shares are the fallback while the lines are
    unknown or unusable.
    """
    if n <= 0:
        return []
    shares = _sector_shares(n, boundaries)
    edges = [0.0]
    for share in shares:
        edges.append(edges[-1] + share * width)
    return [(edges[i], max(edges[i + 1] - edges[i], 0.0)) for i in range(n)]


def _sector_shares(n: int, boundaries: Sequence[float]) -> list[float]:
    """Each sector's share of the lap, normalized; equal shares if the lines are unusable."""
    if n <= 0:
        return []
    usable = len(boundaries) == n + 1 and all(boundaries[i] < boundaries[i + 1] for i in range(n))
    if not usable:
        return [1.0 / n] * n
    span = boundaries[-1] - boundaries[0]
    return [(boundaries[i + 1] - boundaries[i]) / span for i in range(n)]


def _sector_path(
    left: float,
    width: float,
    height: float,
    radius: float,
    *,
    round_left: bool,
    round_right: bool,
) -> QPainterPath:
    """A sector segment rounded only on the bar's outer ends, square where it meets another.

    Rounding an inner edge would curve the segment away from the line and make the joint look
    wider than it is.
    """
    r = max(min(radius, width / 2.0, height / 2.0), 0.0)
    left_r, right_r = (r if round_left else 0.0), (r if round_right else 0.0)
    right, bottom = left + width, height
    path = QPainterPath()
    path.moveTo(left + left_r, 0.0)
    path.lineTo(right - right_r, 0.0)
    if right_r:
        path.quadTo(right, 0.0, right, right_r)
    path.lineTo(right, bottom - right_r)
    if right_r:
        path.quadTo(right, bottom, right - right_r, bottom)
    path.lineTo(left + left_r, bottom)
    if left_r:
        path.quadTo(left, bottom, left, bottom - left_r)
    path.lineTo(left, left_r)
    if left_r:
        path.quadTo(left, 0.0, left + left_r, 0.0)
    path.closeSubpath()
    return path


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
        painter.setBrush(QBrush(QColor(*theme.BAR_TRACK)))
        painter.drawRoundedRect(rect, radius, radius)
        if self._value > 0:
            width = max(rect.width() * self._value, rect.height())
            painter.setBrush(QBrush(self._color))
            fill = QRectF(rect.x(), rect.y(), width, rect.height())
            painter.drawRoundedRect(fill, radius, radius)


STATUS_COLORS = theme.STATUS_COLORS


class SectorBar(QWidget):
    """F1-style sector indicator: one segment per game sector, coloured by how it went.

    Grey = not driven yet, yellow = slower than your kept runs, green = among your fastest,
    purple = your fastest. A thin separator marks each of the game's sector lines.
    """

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
        rects = sector_rects(n, self._boundaries, self.width())
        h = float(self.height())
        radius = h / 2.5
        paths = [
            _sector_path(left, width, h, radius, round_left=i == 0, round_right=i == n - 1)
            for i, (left, width) in enumerate(rects)
        ]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, path in enumerate(paths):
            painter.setBrush(QColor(STATUS_COLORS[self._status[index]]))
            painter.drawPath(path)

        if self._current is not None and 0 <= self._current < n:
            left, width = rects[self._current]
            painter.save()
            painter.setClipPath(paths[self._current])
            if self._progress > 0:
                painter.setBrush(QColor(*theme.BAR_PROGRESS))
                fill = QRectF(left, 0.0, max(width * self._progress, 0.0), h)
                painter.drawRoundedRect(fill, radius, radius)
            painter.restore()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*theme.BAR_OUTLINE), 1.0))
            inset = _sector_path(
                left + 0.5,
                max(width - 1.0, 0.0),
                max(h - 1.0, 0.0),
                radius,
                round_left=self._current == 0,
                round_right=self._current == n - 1,
            )
            painter.drawPath(inset)

        # A line, not a gap: the sector colours meet at the game's line, and this marks it.
        painter.setPen(QPen(QColor(*theme.BAR_SEPARATOR), 1.0))
        for left, _ in rects[1:]:
            painter.drawLine(QPointF(left, 0.5), QPointF(left, h - 0.5))

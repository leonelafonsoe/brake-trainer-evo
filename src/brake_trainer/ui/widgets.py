"""Small reusable widgets and drawn icons."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..models import SectorStatus, group_sizes
from . import theme


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
    purple = your fastest. With more than three sectors each group is split into sub-sectors.
    """

    _SEGMENT_GAP = 2.0
    _GROUP_GAP = 8.0

    def __init__(self, parent: QWidget | None = None, height: int = 9) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._status: tuple[SectorStatus, ...] = ()
        self._current: int | None = None
        self._progress = 0.0

    def set_state(
        self, status: tuple[SectorStatus, ...], current: int | None, progress: float
    ) -> None:
        state = (status, current, round(progress, 2))
        if state != (self._status, self._current, round(self._progress, 2)):
            self._status, self._current, self._progress = status, current, progress
            self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        n = len(self._status)
        if n == 0:
            return
        groups = group_sizes(n)
        total_gap = sum(self._SEGMENT_GAP * (g - 1) for g in groups)
        total_gap += self._GROUP_GAP * (len(groups) - 1)
        seg_w = (self.width() - total_gap) / n
        h = float(self.height())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, index = 0.0, 0
        for size in groups:
            for _ in range(size):
                rect = QRectF(x, 0, seg_w, h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(STATUS_COLORS[self._status[index]]))
                painter.drawRoundedRect(rect, h / 2.5, h / 2.5)
                if index == self._current:
                    painter.setBrush(QColor(255, 255, 255, 110))
                    fill = QRectF(x, 0, max(seg_w * self._progress, 0.0), h)
                    painter.drawRoundedRect(fill, h / 2.5, h / 2.5)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QColor(255, 255, 255, 230))
                    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), h / 2.5, h / 2.5)
                x += seg_w + self._SEGMENT_GAP
                index += 1
            x += self._GROUP_GAP - self._SEGMENT_GAP

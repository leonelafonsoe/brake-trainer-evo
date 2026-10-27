"""The live window: a transparent HUD with the few numbers that matter while driving."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QEnterEvent,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QScreen,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..models import Snapshot, ViewState
from . import theme
from .status import phase_label, status_line
from .widgets import BarWidget, SectorBar

_APPROACH_WINDOW_M = 400.0  # the approach bar starts filling this far from the point


def _px(value: float, scale: float) -> int:
    """A base pixel size at the requested HUD scale, never below one pixel."""
    return max(1, round(value * scale))


def _shadow(widget: QWidget, scale: float) -> None:
    """Soft dark shadow so text stays readable on a fully transparent background."""
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(_px(8, scale))
    fx.setOffset(0, _px(1, scale))
    fx.setColor(QColor(*theme.SHADOW))
    widget.setGraphicsEffect(fx)


def _label(
    text: str = "",
    *,
    size: int = 12,
    color: str = theme.TEXT,
    bold: bool = False,
    scale: float = 1.0,
) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{color}; font-size:{_px(size, scale)}px; font-weight:{'600' if bold else '400'};"
    )
    _shadow(lab, scale)
    return lab


def _caption(text: str, scale: float = 1.0) -> QLabel:
    return _label(text, size=10, color=theme.TEXT_DIM, bold=True, scale=scale)


def _style(widget: QWidget, css: str) -> None:
    """Apply a stylesheet only when it changed (the overlay redraws at 20 Hz)."""
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)


def _text(label: QLabel, text: str) -> None:
    """Set label text only when it changed."""
    if label.text() != text:
        label.setText(text)


class ToolButton(QPushButton):
    """A small painted icon button.

    The glyphs are drawn rather than taken from a font: Unicode symbols such as ``⏸`` are not in
    every UI font and clip or disappear when the font size changes with the HUD scale.
    """

    def __init__(self, kind: str, tip: str, name: str, *, scale: float = 1.0) -> None:
        super().__init__()
        self._kind = kind
        self.setToolTip(tip)
        self.setAccessibleName(name)
        self.setFixedSize(_px(22, scale), _px(22, scale))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # hiding them must not shift the layout
        self.setSizePolicy(policy)

    @property
    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.update()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 (Qt API)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt API)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # QColor does not parse the CSS rgba() string used by the stylesheet; use channels for the
        # dim state and the hex theme colour when hovered.
        color = QColor(theme.TEXT) if self.underMouse() else QColor(*theme.TEXT_DIM_RGBA)
        size = float(min(self.width(), self.height()))
        pen = QPen(color)
        pen.setWidthF(max(1.0, size * 0.085))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = size * 0.26
        if self._kind == "pause":
            bar_w, gap = size * 0.11, size * 0.13
            painter.fillRect(
                QRectF(center.x() - gap - bar_w, center.y() - radius, bar_w, radius * 2), color
            )
            painter.fillRect(
                QRectF(center.x() + gap, center.y() - radius, bar_w, radius * 2), color
            )
        elif self._kind == "play":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(center.x() - radius * 0.8, center.y() - radius),
                        QPointF(center.x() - radius * 0.8, center.y() + radius),
                        QPointF(center.x() + radius, center.y()),
                    ]
                )
            )
        elif self._kind == "settings":
            painter.drawEllipse(center, radius, radius)
            tooth = size * 0.10
            for i in range(8):
                angle = math.pi * i / 4.0
                painter.drawLine(
                    QPointF(
                        center.x() + math.cos(angle) * (radius + tooth * 0.4),
                        center.y() + math.sin(angle) * (radius + tooth * 0.4),
                    ),
                    QPointF(
                        center.x() + math.cos(angle) * (radius + tooth),
                        center.y() + math.sin(angle) * (radius + tooth),
                    ),
                )
            painter.drawEllipse(center, radius * 0.35, radius * 0.35)
        else:  # close
            painter.drawLine(
                QPointF(center.x() - radius, center.y() - radius),
                QPointF(center.x() + radius, center.y() + radius),
            )
            painter.drawLine(
                QPointF(center.x() - radius, center.y() + radius),
                QPointF(center.x() + radius, center.y() - radius),
            )


class OverlayWindow(QWidget):
    settings_requested = Signal()
    quit_requested = Signal()
    toggle_on_top = Signal(bool)
    toggle_learning = Signal(bool)
    moved = Signal(int, int)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._drag_offset: QPoint | None = None
        self._state = ViewState(snapshot=Snapshot())
        self.setWindowTitle("Brake Trainer")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # A HUD must never pull keyboard focus from the game when it appears or changes flags.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._content: QWidget | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._build()
        self._apply_flags()
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.screenRemoved.connect(self._screen_removed)
        self.apply_settings(settings)
        self.update_state(ViewState(snapshot=Snapshot()))

    # ------------------------------------------------------------------ layout

    def _px(self, value: float) -> int:
        return _px(value, self._settings.hud_scale)

    def _build(self) -> None:
        self.setFixedWidth(self._px(300))
        old, self._content = self._content, QWidget(self)
        if old is not None:
            self._outer.removeWidget(old)
            old.deleteLater()
        self._outer.addWidget(self._content)
        scale = self._settings.hud_scale
        root = QVBoxLayout(self._content)
        root.setContentsMargins(self._px(14), self._px(10), self._px(14), self._px(12))
        root.setSpacing(self._px(5))

        top = QHBoxLayout()
        self._dot = _label("●", size=10, color=theme.MUTED, scale=scale)
        self._title = _label("Brake Trainer", size=11, color=theme.TEXT_DIM, scale=scale)
        self._learn_btn = ToolButton("pause", "Pause learning", "Pause learning", scale=scale)
        self._settings_btn = ToolButton("settings", "Settings", "Settings", scale=scale)
        self._quit_btn = ToolButton("close", "Quit", "Quit", scale=scale)
        self._learn_btn.clicked.connect(
            lambda: self.toggle_learning.emit(not self._settings.learning_enabled)
        )
        self._settings_btn.clicked.connect(self.settings_requested)
        self._quit_btn.clicked.connect(self.quit_requested)
        for w in (self._dot, self._title):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self._learn_btn)
        top.addWidget(self._settings_btn)
        top.addWidget(self._quit_btn)
        root.addLayout(top)
        self._set_buttons_visible(False)

        nxt = QHBoxLayout()
        nxt.addWidget(_caption("NEXT BRAKE", scale=scale))
        nxt.addStretch(1)
        self._distance = _label("—", size=20, bold=True, scale=scale)
        # The phase words use a smaller font; a fixed height keeps the row (and the window) still.
        self._distance.setFixedHeight(self._px(24))
        self._distance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nxt.addWidget(self._distance)
        root.addLayout(nxt)
        self._approach = BarWidget(height=self._px(4))
        root.addWidget(self._approach)

        row = QHBoxLayout()
        row.addWidget(_caption("BRAKE", scale=scale))
        self._brake = BarWidget(height=self._px(6))
        row.addWidget(self._brake, 1)
        self._speed = _label("0 km/h", size=11, scale=scale)
        self._speed.setMinimumWidth(self._px(62))
        self._speed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._speed)
        root.addLayout(row)

        self._sectors = SectorBar(height=self._px(9))
        root.addSpacing(self._px(2))
        root.addWidget(self._sectors)

        self._ref = _label("", size=10, color=theme.TEXT_DIM, scale=scale)
        root.addWidget(self._ref)

    def _recenter(self, center: QPoint) -> None:
        """Keep ``center`` in place after the window grew, clamped so it stays on its screen."""
        if not self.isVisible():
            return
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        screen = QGuiApplication.screenAt(center)
        if screen is not None:
            area = screen.availableGeometry()
            x = min(max(x, area.left()), max(area.left(), area.right() - self.width() + 1))
            y = min(max(y, area.top()), max(area.top(), area.bottom() - self.height() + 1))
        self.move(x, y)
        self.moved.emit(self.x(), self.y())

    def _set_buttons_visible(self, visible: bool) -> None:
        self._learn_btn.setVisible(visible)
        self._settings_btn.setVisible(visible)
        self._quit_btn.setVisible(visible)

    def _apply_flags(self) -> None:
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # no taskbar entry and no Alt-Tab competition with the game
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if self._settings.overlay_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self._settings.overlay_click_through:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)

    # ------------------------------------------------------------------ settings & state

    def apply_settings(self, settings: Settings) -> None:
        old = self._settings
        self._settings = settings
        if old.hud_scale != settings.hud_scale:
            center = self.frameGeometry().center() if self.isVisible() else None
            self._build()  # the label fonts and fixed metrics are baked in at build time
            if center is not None:
                # The new content has no final height until the layout has run: recenter on the
                # next event-loop turn, when the window has its new size.
                QTimer.singleShot(0, lambda point=center: self._recenter(point))
        self.setWindowOpacity(settings.overlay_opacity)
        learning = settings.learning_enabled
        self._learn_btn.set_kind("pause" if learning else "play")
        self._learn_btn.setToolTip("Pause learning" if learning else "Resume learning")
        self._learn_btn.setAccessibleName("Pause learning" if learning else "Resume learning")
        self.update()
        if (old.overlay_always_on_top, old.overlay_click_through) != (
            settings.overlay_always_on_top,
            settings.overlay_click_through,
        ):
            was_visible = self.isVisible()
            self._apply_flags()
            if was_visible:
                self.show()
        self.update_state(self._state)  # refresh the status line

    def update_state(self, state: ViewState) -> None:
        self._state = state
        snap = state.snapshot
        if not state.game_running and not state.live:
            _style(self._dot, f"color:{theme.MUTED}; font-size:{self._px(10)}px;")
            _text(self._title, "Waiting for Assetto Corsa EVO…")
        else:
            color = theme.GREEN if state.live else theme.AMBER
            _style(self._dot, f"color:{color}; font-size:{self._px(10)}px;")
            if snap.track and state.live:
                title = f"{snap.track} · {snap.car}"
                _text(self._title, title if len(title) <= 36 else title[:35] + "…")
            else:
                _text(self._title, "Game running — not in a session")

        self._update_distance(state)
        self._brake.set_value(snap.brake, theme.RED if snap.braking else theme.TEXT)
        _text(self._speed, f"{snap.speed_kmh:.0f} km/h")

        if state.live and snap.sector_status:
            self._sectors.set_state(
                snap.sector_status, snap.sector, snap.sector_progress, snap.boundaries
            )
        else:
            self._sectors.set_state((), None, 0.0)

        line = status_line(snap, self._settings, state.live, state.error)
        if line is None:
            if not self._ref.isHidden():
                self._ref.hide()
            if self._ref.toolTip():
                self._ref.setToolTip("")
        else:
            text, colour = line
            _text(self._ref, text)
            _style(
                self._ref,
                f"color:{colour}; font-size:{self._px(10)}px; font-weight:400;",
            )
            if self._ref.toolTip() != state.error:
                self._ref.setToolTip(state.error)
            if self._ref.isHidden():
                self._ref.show()

    def _update_distance(self, state: ViewState) -> None:
        snap, st = state.snapshot, self._settings
        style = "color:{c}; font-size:{s}px; font-weight:{w};"
        if not state.live:
            _text(self._distance, "—")
            _style(self._distance, style.format(c=theme.TEXT_DIM, s=self._px(20), w=700))
            self._approach.set_value(0)
            return
        if snap.next_zone_m is None:
            _text(self._distance, phase_label(snap, st))
            _style(self._distance, style.format(c=theme.TEXT_DIM, s=self._px(14), w=600))
            self._approach.set_value(0)
            return
        dist = snap.next_zone_m
        if dist <= st.here_m * 2:
            color = theme.RED
        elif dist <= snap.lead_m:
            color = theme.AMBER
        else:
            color = theme.TEXT
        _text(self._distance, f"{dist:.0f} m")
        _style(self._distance, style.format(c=color, s=self._px(20), w=700))
        self._approach.set_value(1 - min(dist, _APPROACH_WINDOW_M) / _APPROACH_WINDOW_M, color)

    # ------------------------------------------------------------------ window behaviour

    def move_to_default(self) -> None:
        """Top-centre of the screen under the cursor, so a game on a second monitor is covered."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.adjustSize()
        area = screen.availableGeometry()
        self.move(area.x() + (area.width() - self.width()) // 2, area.y() + 16)

    def _screen_removed(self, screen: QScreen) -> None:
        """Bring the HUD back if the monitor it was on is unplugged or disabled."""
        if self.screen() is not screen and QGuiApplication.screenAt(self.frameGeometry().center()):
            return
        self.move_to_default()
        self.moved.emit(self.x(), self.y())

    def place(self, x: int | None, y: int | None) -> None:
        """Restore a saved position, or use the default if it is unset or off every screen."""
        if x is not None and y is not None:
            self.adjustSize()
            rect = QRect(x, y, self.width(), self.height())
            screen = QGuiApplication.screenAt(rect.center())
            if screen is not None and screen.availableGeometry().intersects(rect):
                self.move(x, y)
                return
        self.move_to_default()

    def reset_position(self) -> None:
        self.move_to_default()
        self.moved.emit(self.x(), self.y())

    def paintEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Transparent by default. A near-invisible fill keeps the window grabbable by mouse
        (fully transparent pixels would let clicks fall through to the game)."""
        bg = self._settings.overlay_background
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*theme.OVERLAY_BG, max(1, round(255 * bg))))
        painter.drawRoundedRect(self.rect(), 12, 12)

    def enterEvent(self, event: object) -> None:  # noqa: N802
        self._set_buttons_visible(True)

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._set_buttons_visible(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit(self.x(), self.y())

    def contextMenuEvent(self, event: object) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.addAction("Settings…", self.settings_requested.emit)
        learn = QAction("Learn braking points", menu, checkable=True)
        learn.setChecked(self._settings.learning_enabled)
        learn.toggled.connect(self.toggle_learning)
        menu.addAction(learn)
        pin = QAction("Always on top", menu, checkable=True)
        pin.setChecked(self._settings.overlay_always_on_top)
        pin.toggled.connect(self.toggle_on_top)
        menu.addAction(pin)
        menu.addAction("Reset position", self.reset_position)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_requested.emit)
        menu.exec(self.cursor().pos())

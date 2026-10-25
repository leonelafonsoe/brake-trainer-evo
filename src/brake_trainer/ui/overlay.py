"""The live window: a transparent HUD with the few numbers that matter while driving."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
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


def _shadow(widget: QWidget) -> None:
    """Soft dark shadow so text stays readable on a fully transparent background."""
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(8)
    fx.setOffset(0, 1)
    fx.setColor(QColor(0, 0, 0, 230))
    widget.setGraphicsEffect(fx)


def _label(
    text: str = "", *, size: int = 12, color: str = theme.TEXT, bold: bool = False
) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{color}; font-size:{size}px; font-weight:{'600' if bold else '400'};")
    _shadow(lab)
    return lab


def _caption(text: str) -> QLabel:
    return _label(text, size=10, color=theme.TEXT_DIM, bold=True)


def _style(widget: QWidget, css: str) -> None:
    """Apply a stylesheet only when it changed (the overlay redraws at 20 Hz)."""
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)


def _text(label: QLabel, text: str) -> None:
    """Set label text only when it changed."""
    if label.text() != text:
        label.setText(text)


def _tool_button(text: str, tip: str, name: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setToolTip(tip)
    btn.setAccessibleName(name)
    btn.setFixedSize(22, 22)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent; border: none; color: {theme.TEXT_DIM};"
        f" font-size: 14px; }} QPushButton:hover {{ color: {theme.TEXT}; }}"
    )
    policy = btn.sizePolicy()
    policy.setRetainSizeWhenHidden(True)  # hiding them must not shift the layout
    btn.setSizePolicy(policy)
    return btn


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
        self.setFixedWidth(300)
        self._build()
        self._apply_flags()
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.screenRemoved.connect(self._screen_removed)
        self.apply_settings(settings)
        self.update_state(ViewState(snapshot=Snapshot()))

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(5)

        top = QHBoxLayout()
        self._dot = _label("●", size=10, color=theme.MUTED)
        self._title = _label("Brake Trainer", size=11, color=theme.TEXT_DIM)
        self._learn_btn = _tool_button("⏸", "Pause learning", "Pause learning")
        self._settings_btn = _tool_button("⚙", "Settings", "Settings")
        self._quit_btn = _tool_button("✕", "Quit", "Quit")
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
        nxt.addWidget(_caption("NEXT BRAKE"))
        nxt.addStretch(1)
        self._distance = _label("—", size=20, bold=True)
        # The phase words use a smaller font; a fixed height keeps the row (and the window) still.
        self._distance.setFixedHeight(24)
        self._distance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nxt.addWidget(self._distance)
        root.addLayout(nxt)
        self._approach = BarWidget(height=4)
        root.addWidget(self._approach)

        row = QHBoxLayout()
        row.addWidget(_caption("BRAKE"))
        self._brake = BarWidget(height=6)
        row.addWidget(self._brake, 1)
        self._speed = _label("0 km/h", size=11)
        self._speed.setMinimumWidth(62)
        self._speed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._speed)
        root.addLayout(row)

        self._sectors = SectorBar(height=9)
        root.addSpacing(2)
        root.addWidget(self._sectors)

        self._ref = _label("", size=10, color=theme.TEXT_DIM)
        root.addWidget(self._ref)

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
        self.setWindowOpacity(settings.overlay_opacity)
        learning = settings.learning_enabled
        self._learn_btn.setText("⏸" if learning else "▶")
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
            _style(self._dot, f"color:{theme.MUTED}; font-size:10px;")
            _text(self._title, "Waiting for Assetto Corsa EVO…")
        else:
            color = theme.GREEN if state.live else theme.AMBER
            _style(self._dot, f"color:{color}; font-size:10px;")
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
            _style(self._ref, f"color:{colour}; font-size:10px; font-weight:400;")
            if self._ref.toolTip() != state.error:
                self._ref.setToolTip(state.error)
            if self._ref.isHidden():
                self._ref.show()

    def _update_distance(self, state: ViewState) -> None:
        snap, st = state.snapshot, self._settings
        style = "color:{c}; font-size:{s}px; font-weight:{w};"
        if not state.live:
            _text(self._distance, "—")
            _style(self._distance, style.format(c=theme.TEXT_DIM, s=20, w=700))
            self._approach.set_value(0)
            return
        if snap.next_zone_m is None:
            _text(self._distance, phase_label(snap, st))
            _style(self._distance, style.format(c=theme.TEXT_DIM, s=14, w=600))
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
        _style(self._distance, style.format(c=color, s=20, w=700))
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
        painter.setBrush(QColor(12, 14, 18, max(1, round(255 * bg))))
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

"""Colours and the application style sheet."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from ..models import SectorStatus

BG = "#14171c"
PANEL = "#1b1f26"
BORDER = "#2a303a"
TEXT = "#e6e9ef"
MUTED = "#8b93a1"
GREEN = "#3ddc84"
AMBER = "#ffb020"
RED = "#ff4d4f"
ACCENT = "#4da3ff"
TEXT_DIM = "rgba(255, 255, 255, 175)"
BUTTON_TEXT = "#0b0e12"  # dark text on ACCENT

# F1-style sector colours
SECTOR_PENDING = "#6b7280"
SECTOR_SLOWER = "#ffd23f"
SECTOR_GOOD = "#3ddc84"
SECTOR_BEST = "#b266ff"

STATUS_COLORS = {
    SectorStatus.PENDING: SECTOR_PENDING,
    SectorStatus.SLOWER: SECTOR_SLOWER,
    SectorStatus.GOOD: SECTOR_GOOD,
    SectorStatus.BEST: SECTOR_BEST,
}

STYLE = f"""
QWidget {{ color: {TEXT}; font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; }}
QDialog {{ background: {BG}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL}; border-radius: 6px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 14px; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
               padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: {BUTTON_TEXT}; border: none;
                               font-weight: 600; }}
QPushButton[primary="true"]:disabled {{ background: {BORDER}; color: {MUTED}; }}
QDoubleSpinBox, QSpinBox, QLineEdit {{ background: {BG}; border: 1px solid {BORDER};
               border-radius: 5px; padding: 4px 6px; min-width: 110px; }}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QDoubleSpinBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: {MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QTreeWidget {{ background: {BG}; border: 1px solid {BORDER}; outline: 0; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {ACCENT}; color: {BUTTON_TEXT}; }}
QTreeWidget::item:disabled {{ color: {MUTED}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; padding: 5px; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {BORDER}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
"""


def palette() -> QPalette:
    """The dark palette native controls use, so Fusion does not draw light widgets on dark QSS."""
    pal = QPalette()
    for role, colour in (
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, BG),
        (QPalette.ColorRole.AlternateBase, PANEL),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, PANEL),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.ToolTipBase, PANEL),
        (QPalette.ColorRole.ToolTipText, TEXT),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, BUTTON_TEXT),
        (QPalette.ColorRole.PlaceholderText, MUTED),
    ):
        pal.setColor(role, QColor(colour))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(MUTED))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(MUTED))
    return pal

"""About tab: version, credits and licence."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ... import __version__
from .. import theme

_ABOUT_HTML = (
    "<style>a {{ color: {accent}; }}</style>"
    "<h3>Brake Trainer EVO {version}</h3>"
    "<p>Learns where you brake on each track and car, and beeps as you approach those points.</p>"
    "<p><b>Credits</b><br>"
    "&bull; <a href='https://github.com/glebulon/acevo-sdk'>acevo-sdk</a> by Gleb Zverinskiy, "
    "which reads the game's telemetry. Without it this would not be possible.<br>"
    "&bull; <a href='https://www.overtake.gg/downloads/brake-trainer.32511/'>Brake Trainer</a> "
    "by AugGust, the original app for Assetto Corsa that inspired this project.</p>"
    "<p><b>Vibe coded.</b> Written almost entirely by an AI assistant (Claude) together with the "
    "maintainer. Expect rough edges and please report bugs.</p>"
    "<p>License: PolyForm Noncommercial 1.0.0. Free to use, share and modify for "
    "non-commercial purposes; not for sale.</p>"
)


class AboutPageMixin:
    def _about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        label = QLabel(_ABOUT_HTML.format(version=__version__, accent=theme.ACCENT))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(theme.ACCENT))
        label.setPalette(palette)
        layout.addWidget(label)
        return page

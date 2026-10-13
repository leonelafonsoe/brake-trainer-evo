"""The application icon, drawn in code (a brake disc with a red caliper).

Drawing it at runtime means the window, taskbar and tray icons need no image files, so nothing
extra has to be bundled into the executable. ``scripts/make_icon.py`` renders the same drawing
into ``packaging/icon.ico`` for the .exe, the installer and shortcuts.
"""

from __future__ import annotations

import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

_BG_TOP, _BG_BOTTOM = QColor("#222831"), QColor("#0e1115")
_DISC, _HUB, _CALIPER = QColor("#e3e7ee"), QColor("#b9c0cc"), QColor("#ff4d4f")


def draw_icon(size: int) -> QImage:
    """Render the icon at ``size`` x ``size`` pixels with a transparent background."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 256.0, size / 256.0)  # draw in a 256 x 256 space

    gradient = QLinearGradient(0, 8, 0, 248)
    gradient.setColorAt(0, _BG_TOP)
    gradient.setColorAt(1, _BG_BOTTOM)
    painter.setPen(QPen(QColor(255, 255, 255, 40), 2))
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)

    centre = QPointF(128, 128)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_DISC)  # the disc: a thick ring
    painter.drawEllipse(centre, 84, 84)
    painter.setBrush(_BG_BOTTOM)
    painter.drawEllipse(centre, 58, 58)
    painter.setBrush(_HUB)  # hub with a centre hole
    painter.drawEllipse(centre, 34, 34)
    painter.setBrush(_BG_BOTTOM)
    painter.drawEllipse(centre, 11, 11)

    if size >= 48:  # cooling holes only where they stay visible
        for k in range(8):
            angle = k * 45 + 22.5
            holes = QPointF(0, -71)
            transform = painter.transform()
            painter.translate(centre)
            painter.rotate(angle)
            painter.drawEllipse(holes, 7.5, 7.5)
            painter.setTransform(transform)

    caliper = QPen(_CALIPER, 26)  # the caliper: a thick red arc around the disc
    caliper.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(caliper)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(28, 28, 200, 200), 24 * 16, 78 * 16)
    painter.end()
    return image


def app_icon() -> QIcon:
    """The icon with every common size, so Windows picks a crisp one for each place."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_icon(size)))
    return icon


def png_bytes(size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    # PySide6 accepts the format name as str at runtime; its type stubs say bytes
    draw_icon(size).save(buffer, "PNG")  # type: ignore[call-overload]
    buffer.close()
    return bytes(data.data())


def dib_bytes(image: QImage) -> bytes:
    """An icon entry as an uncompressed 32-bit bitmap (DIB), the form every Windows version and
    the shell read reliably for sizes below 256 px."""
    width, height = image.width(), image.height()
    argb = image.convertToFormat(QImage.Format.Format_ARGB32)
    stride, raw = argb.bytesPerLine(), bytes(argb.constBits())  # B, G, R, A per pixel
    rows = [raw[y * stride : y * stride + 4 * width] for y in range(height)]
    pixels = b"".join(reversed(rows))  # bitmaps are stored bottom-up
    mask = bytes(((width + 31) // 32) * 4 * height)  # AND mask: unused, alpha rules
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    return header + pixels + mask


def ico_entry(size: int) -> bytes:
    """The data for one .ico entry: PNG for 256 px, a plain bitmap for the smaller sizes."""
    return png_bytes(size) if size >= 256 else dib_bytes(draw_icon(size))


def pack_ico(images: dict[int, bytes]) -> bytes:
    """Pack entries (keyed by pixel size) into an .ico file, see :func:`ico_entry`."""
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for size in sizes:
        png = images[size]
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs

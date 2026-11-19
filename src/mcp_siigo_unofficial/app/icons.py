"""Tray and window icons, drawn with QPainter at run time.

The icon is a white cloud with an arch bridge made of the letters "ii". No image
files and no image-format plugins are needed (plan D20). The write-mode
icon adds a red warning badge, and automatic approval turns the whole icon red
(plan section 5.1).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

BRAND = QColor("#1E5AA8")
BRAND_DARK = QColor("#123A6E")
WARNING = QColor("#D32F2F")
SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def _paint(size: int, write_mode: bool, automatic: bool = False) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # Rounded square background.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(WARNING if automatic else BRAND))
    painter.drawRoundedRect(QRectF(0.04 * s, 0.04 * s, 0.92 * s, 0.92 * s), 0.22 * s, 0.22 * s)

    # A white cloud with an arch bridge inside it. The two letters "ii" are the
    # bridge: their stems hold the road and their dots sit above it. The bridge
    # is cut out in the background color (the MCP is a bridge to Siigo's cloud).
    def p(x: float, y: float) -> QPointF:
        return QPointF(x * s / 100, y * s / 100)

    cloud = QPainterPath(p(26, 79))
    cloud.lineTo(p(76, 79))
    for control, end in (
        ((92, 79), (92, 63)),
        ((92, 48), (78, 46)),
        ((76, 21), (55, 21)),
        ((42, 21), (36, 32)),
        ((30, 28), (24, 31)),
        ((14, 35), (14, 46)),
        ((6, 50), (6, 63)),
        ((6, 79), (26, 79)),
    ):
        cloud.quadTo(p(*control), p(*end))
    cloud.closeSubpath()
    painter.setBrush(QBrush(QColor("white")))
    painter.drawPath(cloud)

    background = WARNING if automatic else BRAND
    pen = QPen(background, max(1.0, 0.06 * s))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(p(18, 57), p(82, 57))  # the road
    painter.drawLine(p(38, 57), p(38, 72))  # the two "i" stems
    painter.drawLine(p(62, 57), p(62, 72))
    arch = QPainterPath(p(38, 72))
    arch.quadTo(p(50, 60), p(62, 72))
    painter.drawPath(arch)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(background))
    dot = max(0.8, 0.042 * s)
    painter.drawEllipse(p(38, 46), dot, dot)  # the two "i" dots
    painter.drawEllipse(p(62, 46), dot, dot)

    if write_mode and not automatic:
        # Red badge with a white exclamation mark, bottom right.
        r = 0.27 * s
        center = QPointF(s - r - 0.01 * s, s - r - 0.01 * s)
        painter.setPen(QPen(QColor("white"), max(1.0, 0.05 * s)))
        painter.setBrush(QBrush(WARNING))
        painter.drawEllipse(center, r, r)
        mark = QPen(QColor("white"), max(1.2, 0.07 * s))
        mark.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(mark)
        painter.drawLine(
            QPointF(center.x(), center.y() - 0.5 * r), QPointF(center.x(), center.y() + 0.1 * r)
        )
        painter.drawPoint(QPointF(center.x(), center.y() + 0.5 * r))
    painter.end()
    return pixmap


def app_icon(write_mode: bool = False, automatic: bool = False) -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_paint(size, write_mode, automatic))
    return icon

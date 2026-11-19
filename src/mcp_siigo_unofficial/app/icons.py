"""Tray and window icons, drawn with QPainter at run time.

No image files and no image-format plugins are needed (plan D20). The write-mode
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

    # A bridge: two pillars and an arch (the MCP is a bridge to the Siigo API).
    pen = QPen(QColor("white"), max(1.5, 0.09 * s))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arch = QPainterPath(QPointF(0.2 * s, 0.62 * s))
    arch.quadTo(QPointF(0.5 * s, 0.12 * s), QPointF(0.8 * s, 0.62 * s))
    painter.drawPath(arch)
    painter.drawLine(QPointF(0.14 * s, 0.62 * s), QPointF(0.86 * s, 0.62 * s))
    painter.drawLine(QPointF(0.32 * s, 0.62 * s), QPointF(0.32 * s, 0.82 * s))
    painter.drawLine(QPointF(0.68 * s, 0.62 * s), QPointF(0.68 * s, 0.82 * s))

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

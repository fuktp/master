"""Generate a small vector CAIO mark and a multi-resolution ICO with existing Qt."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen


def main() -> None:
    assets = Path(__file__).resolve().parents[1] / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "caio.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="8" y="8" width="240" height="240" rx="52" fill="#00338D"/><path d="M176 80a68 68 0 1 0 0 96" fill="none" stroke="white" stroke-width="22" stroke-linecap="round"/><path d="M121 128h67" stroke="#00A3E0" stroke-width="12" stroke-linecap="round"/><circle cx="190" cy="128" r="17" fill="#00A3E0"/></svg>'
    )
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        canvas = QImage(512, 512, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#00338D"))
        painter.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
        pen = QPen(QColor("white"), 22)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(60, 60, 136, 136), 45 * 16, 270 * 16)
        pen = QPen(QColor("#00A3E0"), 12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(121, 128, 188, 128)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#00A3E0"))
        painter.drawEllipse(QRectF(173, 111, 34, 34))
        painter.end()
        image = canvas.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if size == 256:
            image.save(str(assets / "caio.png"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        images.append((size, bytes(data)))
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    body = b""
    for size, data in images:
        header += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)
    (assets / "caio.ico").write_bytes(header + body)


if __name__ == "__main__":
    main()

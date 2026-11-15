"""Генерує packaging/icon.ico: оригінальний простий значок «розгорнутий зошит із позначкою».

Запуск: .venv/Scripts/python packaging/make_icon.py  (потрібен лише PySide6).
Кольори — з токенів світлої теми застосунку.
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF  # noqa: E402

from journal.ui.theme import TOKENS  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
BASE = 256.0


def draw(size: int) -> QImage:
    t = TOKENS["light"]
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / BASE, size / BASE)

    # Тло: заокруглений квадрат кольору акценту.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(t["accent"]))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)

    # Розгорнутий зошит: дві сторінки, трохи нахилені до середини.
    page = QColor(t["surface"])
    p.setBrush(page)
    left = QPolygonF([QPointF(40, 84), QPointF(124, 100), QPointF(124, 204), QPointF(40, 188)])
    right = QPolygonF([QPointF(216, 84), QPointF(132, 100), QPointF(132, 204), QPointF(216, 188)])
    p.drawPolygon(left)
    p.drawPolygon(right)

    # Рядки на лівій сторінці.
    pen = QPen(QColor(t["control_border"]), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for y in (122, 144, 166):
        p.drawLine(QPointF(54, y), QPointF(108, y + 4))

    # Позначка «виконано» на правій сторінці.
    pen = QPen(QColor(t["mark_late"]), 15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    check = QPainterPath(QPointF(152, 146))
    check.lineTo(171, 166)
    check.lineTo(200, 124)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(check)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return header + entries + blobs


def main() -> None:
    _app = QGuiApplication(sys.argv[:1])
    images = [(size, png_bytes(draw(size))) for size in SIZES]
    target = Path(__file__).resolve().parent / "icon.ico"
    target.write_bytes(build_ico(images))
    print(f"{target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

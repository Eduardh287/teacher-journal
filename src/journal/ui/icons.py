"""Іконки у стилі Lucide (MIT), вбудовані як SVG — без зовнішніх файлів і залежностей.

Колір підставляється під час малювання, тому одна іконка працює в обох темах.
"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "book": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
    '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    "settings": '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3"/>'
    '<path d="M14 2v4M8 10v4M16 18v4"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
    '<path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    "cap": '<path d="M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/><path d="M22 10v6"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41'
    'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
}


def pixmap(name: str, color: str, size: int = 20, stroke: float = 2.0) -> QPixmap:
    """Малює іконку заданого кольору. Подвійна роздільність — для чітких екранів."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    )
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str, selected_color: str | None = None, size: int = 20) -> QIcon:
    """QIcon зі звичайним кольором і (необов'язково) окремим кольором для вибраного стану."""
    result = QIcon(pixmap(name, color, size))
    if selected_color:
        result.addPixmap(pixmap(name, selected_color, size), QIcon.Mode.Selected)
    return result

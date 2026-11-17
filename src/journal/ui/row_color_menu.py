"""Меню «Колір» рядка учня: шість кольорів зі зразком + «Без кольору». Спільне для класів і журналу."""
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from journal.ui import theme

SWATCH_SIZE = 16


def swatch_icon(token: str) -> QIcon:
    """Квадратик із закругленими кутами кольору рядка (обводка — щоб світлі зразки було видно)."""
    pixmap = QPixmap(SWATCH_SIZE, SWATCH_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(theme.color("control_border")), 1))
    painter.setBrush(QColor(theme.color(token)))
    painter.drawRoundedRect(1, 1, SWATCH_SIZE - 2, SWATCH_SIZE - 2, 3, 3)
    painter.end()
    return QIcon(pixmap)


def build_color_menu(
    parent: QWidget, current: str | None, on_choose: Callable[[str | None], None], title: str | None = None
) -> QMenu:
    """Меню вибору кольору. Поточний колір відмічений; on_choose отримує ключ або None («Без кольору»)."""
    menu = QMenu(title, parent)
    for key, (name, token) in theme.ROW_COLORS.items():
        action = menu.addAction(swatch_icon(token), name)
        action.setCheckable(True)
        action.setChecked(key == current)
        action.triggered.connect(lambda _checked=False, k=key: on_choose(k))
    menu.addSeparator()
    none_action: QAction = menu.addAction("Без кольору")
    none_action.triggered.connect(lambda _checked=False: on_choose(None))
    return menu

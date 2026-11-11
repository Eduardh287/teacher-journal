"""Невеликі будівельні блоки інтерфейсу, спільні для всіх вікон."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from journal.ui import icons, theme


def label(text: str = "", *, object_name: str = "", muted: bool = False, wrap: bool = False) -> QLabel:
    """QLabel з потрібним стилем (ім'я об'єкта або «приглушений» текст)."""
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    if muted:
        widget.setProperty("muted", True)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, *, variant: str = "", icon_name: str = "") -> QPushButton:
    """Кнопка: variant = "" (звичайна), "primary" (акцентна) або "ghost" (без рамки)."""
    widget = QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    if icon_name:
        tone = "accent_text" if variant == "primary" else "muted"
        widget.setIcon(icons.icon(icon_name, theme.color(tone), size=16))
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def field(caption: str, edit: QLineEdit) -> QWidget:
    """Поле вводу з підписом над ним (сучасний варіант замість форми «підпис: поле»)."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    caption_label = QLabel(caption)
    caption_label.setProperty("fieldLabel", True)
    layout.addWidget(caption_label)
    layout.addWidget(edit)
    return box


def card() -> tuple[QFrame, QVBoxLayout]:
    """Картка з рамкою й заокругленням. Повертає (картка, її layout)."""
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(12)
    return frame, layout


def brand_mark(size: int = 40) -> QLabel:
    """Логотип: індиго-квадрат з іконкою академічної шапки."""
    mark = QLabel()
    mark.setObjectName("BrandMark")
    mark.setFixedSize(size, size)
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setPixmap(icons.pixmap("cap", theme.color("accent_text"), size=int(size * 0.55)))
    return mark

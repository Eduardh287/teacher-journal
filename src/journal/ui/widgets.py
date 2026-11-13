"""Невеликі будівельні блоки інтерфейсу, спільні для всіх вікон."""
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

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


class ElidedLabel(QLabel):
    """Однорядкова мітка: довгий текст обрізається «…» праворуч і не розпирає макет.

    Мінімальна ширина ~0, підказка з повним текстом з'являється лише коли текст обрізано.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def is_elided(self) -> bool:
        return self.fontMetrics().horizontalAdvance(self.text()) > self.contentsRect().width()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment()), text)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            if self.is_elided():
                QToolTip.showText(event.globalPos(), self.text(), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


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

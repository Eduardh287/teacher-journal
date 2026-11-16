"""Невеликі будівельні блоки інтерфейсу, спільні для всіх вікон."""
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from journal.logging_setup import log_failure
from journal.ui import icons, theme

SAVE_ERROR_TEXT = "Не вдалося зберегти зміни"


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


def error_label() -> QLabel:
    """Прихований рядок помилки (червоний блок): його показують через show()."""
    widget = QLabel()
    widget.setProperty("error", True)
    widget.setWordWrap(True)
    widget.hide()
    return widget


def segment_button(text: str, *, reserve_bold: bool = True) -> QPushButton:
    """Кнопка-сегмент (перемикач). Вибрана має жирний шрифт і стає ширшою — резервуємо місце, щоб текст не обрізався."""
    widget = button(text)
    widget.setProperty("segment", True)
    widget.setCheckable(True)
    if reserve_bold:
        bold = widget.font()
        bold.setBold(True)
        widget.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 56)
    return widget


def confirm(parent: QWidget | None, text: str, accept_text: str) -> bool:
    """Підтвердження дії; кнопка за замовчуванням — «Скасувати»."""
    box = QMessageBox(QMessageBox.Icon.Question, "Підтвердження", text, parent=parent)
    accept = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is accept


class FormDialog(QDialog):
    """Основа діалогів-форм: заголовок, `body` з полями 32/28, рядок помилки й безпечний виклик сервісу.

    `heading` — великий заголовок у вікні (за замовчуванням — назва вікна, "" — без заголовка).
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        heading: str | None = None,
        width: int = 440,
        fixed_width: bool = False,
        margins: tuple[int, int] = (32, 28),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        if fixed_width:
            self.setFixedWidth(width)
        else:
            self.setMinimumWidth(width)
        self.error_label = error_label()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins, *margins)
        self.body.setSpacing(14)
        heading = title if heading is None else heading
        if heading:
            self.body.addWidget(label(heading, object_name="EmptyTitle"))

    def show_error(self, text: str) -> None:
        """Показує помилку прямо в діалозі (без спливаючих вікон)."""
        self.error_label.setText(text)
        self.error_label.show()

    def add_submit(
        self, text: str, slot: Callable, layout: QBoxLayout | None = None, *, default: bool = True
    ) -> QPushButton:
        """Головна кнопка (за замовчуванням — Enter у будь-якому полі запускає дію)."""
        submit = button(text, variant="primary")
        submit.setDefault(default)
        submit.setMinimumHeight(40)
        submit.clicked.connect(slot)
        (self.body if layout is None else layout).addWidget(submit)
        return submit

    def error_text(self, error: Exception) -> str:
        return str(error)

    def run(
        self,
        call: Callable[[], Any],
        error_cls: type[Exception],
        log_message: str,
        fallback_text: str = SAVE_ERROR_TEXT,
    ) -> tuple[bool, Any]:
        """Виконує call. Повертає (успіх, результат); `error_cls` показує його текст, решта — fallback_text.

        Доменну помилку call має кидати ПОЗА блоком with сервісу, щоб транзакція відкотилась.
        """
        self.error_label.hide()
        try:
            return True, call()
        except error_cls as error:
            self.show_error(self.error_text(error))
        except Exception:
            log_failure(log_message)
            self.show_error(fallback_text)
        return False, None


class EntityCard(QFrame):
    """Клікабельна картка (клас чи журнал): назва, підпис, нижній рядок і позначка «Архів»."""

    clicked = Signal()

    def __init__(self, title: str, subtitle: str, footer: str, archived: bool = False) -> None:
        super().__init__()
        self.setObjectName("ClassCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(4)
        top = QHBoxLayout()
        title_label = ElidedLabel(title)
        title_label.setObjectName("CardBig")
        top.addWidget(title_label, 1)
        if archived:
            top.addWidget(label("Архів", object_name="Badge"), alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addWidget(label(subtitle, muted=True))
        layout.addStretch(1)
        layout.addWidget(label(footer))
        # Дочірні мітки пропускають події миші до картки: hover і клік працюють на всій площі.
        for child in self.findChildren(QLabel):
            if not isinstance(child, ElidedLabel):  # підказка потрібна самій мітці
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class EmptyState(QWidget):
    """«Порожній стан»: картка із заголовком, підказкою та кнопкою дії (з круглою іконкою, якщо задано `icon`)."""

    def __init__(
        self,
        title: str,
        hint: str = "",
        action: tuple[str, Callable] | None = None,
        *,
        icon: str = "",
        action_icon: str = "",
        vertical_padding: int = 40,
    ) -> None:
        super().__init__()
        self._icon, self._action_icon = icon, action_icon
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame, layout = card()
        layout.setContentsMargins(40, vertical_padding, 40, vertical_padding)
        self.badge = None
        if icon:
            self.badge = QLabel()
            self.badge.setObjectName("Avatar")  # м'який індиго-кружок
            self.badge.setFixedSize(56, 56)
            self.badge.setStyleSheet("border-radius: 28px;")
            self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(6)
        self.title_label = label(title, object_name="EmptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        self.hint_label = None
        if hint:
            self.hint_label = label(hint, muted=True)
            self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.hint_label)
        self.action = None
        if action:
            if icon:
                layout.addSpacing(10)
            self.action = button(action[0], variant="primary")
            self.action.clicked.connect(action[1])
            layout.addWidget(self.action, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(frame)
        outer.addStretch(1)
        self.refresh_icons()

    def refresh_icons(self) -> None:
        """Перемальовує іконки кольором поточної теми."""
        if self.badge is not None:
            self.badge.setPixmap(icons.pixmap(self._icon, theme.color("accent"), size=26))
        if self.action is not None and self._action_icon:
            self.action.setIcon(icons.icon(self._action_icon, theme.color("accent_text"), size=16))


def card_grid(scroll: QScrollArea, cards: Sequence[QWidget], columns: int = 3) -> None:
    """Розкладає картки сіткою по `columns` у рядку в області прокручування (притиснуті догори)."""
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(16)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    for index, item in enumerate(cards):
        grid.addWidget(item, index // columns, index % columns)
    grid.setRowStretch(len(cards) // columns + 1, 1)
    scroll.setWidget(host)


class CardListView(QWidget):
    """Сторінка-список: заголовок, «Показати архівні» + кнопка створення, сітка карток або порожній стан."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        new_text: str,
        on_new: Callable,
        on_filter: Callable,
        empty: QWidget,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label(title, object_name="PageTitle"))
        layout.addWidget(label(subtitle, muted=True))
        layout.addSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        header.addStretch(1)
        self.archived_check = QCheckBox("Показати архівні")
        self.archived_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.archived_check.toggled.connect(lambda _: on_filter())
        header.addWidget(self.archived_check)
        self.new_button = button(new_text, variant="primary")
        self.new_button.clicked.connect(on_new)
        header.addWidget(self.new_button)
        layout.addLayout(header)
        layout.addSpacing(8)

        self.list_stack = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.list_stack.addWidget(self.scroll)  # 0 — картки
        self.list_stack.addWidget(empty)        # 1 — порожньо
        layout.addWidget(self.list_stack, 1)

    def show_cards(self, cards: Sequence[QWidget]) -> None:
        """Показує сітку карток або (якщо їх немає) порожній стан."""
        if cards:
            card_grid(self.scroll, cards)
        self.list_stack.setCurrentIndex(0 if cards else 1)


class SettingsCard(QFrame):
    """Картка сторінки «Налаштування»: заголовок, підказка, далі `body`.

    `add_feedback()` додає рядки стану й помилки."""

    def __init__(self, title: str, hint: str, *, wrap_hint: bool = False) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 24, 24, 24)
        self.body.setSpacing(12)
        self.body.addWidget(label(title, object_name="CardTitle"))
        self.body.addWidget(label(hint, muted=True, wrap=wrap_hint))
        self.status = label("", muted=True, wrap=True)
        self.status.hide()
        self.error = error_label()

    def add_feedback(self) -> None:
        self.body.addWidget(self.status)
        self.body.addWidget(self.error)

    def show_status(self, text: str) -> None:
        self.error.hide()
        self.status.setText(text)
        self.status.show()

    def show_error(self, text: str) -> None:
        self.status.hide()
        self.error.setText(text)
        self.error.show()

"""Панель «Проведені уроки»: № уроку в семестрі, дата й тема поруч із таблицею журналу.

Лише для читання: редагування й видалення панель не виконує, а просить сторінку сигналами.
Усі кольори беруться з journal.ui.theme (theme.color) у момент наповнення.
"""
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from journal.services.journal_types import LessonInfo
from journal.ui import theme
from journal.ui.journal_dialogs import LESSON_TYPES

NUMBER_WIDTH = 36
DATE_WIDTH = 56
NO_TOPIC_TEXT = "тема не вказана"
TEXT_PADDING = 4  # відступ усередині клітинки (як у QSS панелі)
TEXT_SLACK = 10   # запас по ширині на переноси й межу клітинки

# Тло рядка за типом уроку (звичайний урок — без тла)
_TINT = {"test": "lesson_test_soft", "lab": "lesson_lab_soft", "independent": "lesson_independent_soft"}


def lesson_row_text(lesson: LessonInfo) -> str:
    """Текст стовпця «Тема»: для звичайного уроку — тема (або порожньо), для решти — «Тип: тема»."""
    topic = lesson.topic or ""
    if lesson.lesson_type == "regular":
        return topic
    name = LESSON_TYPES[lesson.lesson_type][0]
    return f"{name}: {topic}" if topic else name


class _TintDelegate(QStyledItemDelegate):
    """Малює тло рядка за типом уроку (стилі теми інакше ігнорують колір елемента)."""

    def paint(self, painter, option, index) -> None:
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is not None and not option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, brush)
        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        """Висота за реальною шириною стовпця (з запасом на відступи), щоб текст не обрізався трьома крапками."""
        hint = super().sizeHint(option, index)
        if index.column() != 2:
            return hint
        width = self.parent().columnWidth(2) - 2 * TEXT_PADDING - TEXT_SLACK
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft)
        rect = option.fontMetrics.boundingRect(0, 0, max(width, 20), 10000, flags, index.data() or "")
        hint.setHeight(rect.height() + 2 * TEXT_PADDING + 4)
        return hint


class LessonPanel(QWidget):
    """Список проведених уроків семестру (№ = номер стовпця таблиці + 1)."""

    lesson_selected = Signal(int)          # клік по рядку
    lesson_edit_requested = Signal(int)    # подвійний клік / меню
    lesson_delete_requested = Signal(int)  # меню

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LessonPanel")
        self._lessons: list[LessonInfo] = []
        self._read_only = False
        self._selected_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)
        self.title = QLabel("Проведені уроки")
        self.title.setObjectName("LessonPanelTitle")
        font = self.title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.title.setFont(font)
        layout.addWidget(self.title)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("LessonTable")
        self.table.setHorizontalHeaderLabels(["№", "Дата", "Тема"])
        self.table.horizontalHeaderItem(2).setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        self.table.setColumnWidth(0, NUMBER_WIDTH)
        self.table.setColumnWidth(1, DATE_WIDTH)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # клавіатура лишається в таблиці журналу
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Вужчі відступи, ніж у загальній темі: інакше «№» і «12.11» не вміщаються (кольорів не торкаємось).
        self.table.setStyleSheet("QTableWidget#LessonTable::item { padding: 4px 4px; }")
        self.table.setItemDelegate(_TintDelegate(self.table))
        header.sectionResized.connect(lambda *_: self._fit_rows())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.cellClicked.connect(self._on_clicked)
        self.table.cellDoubleClicked.connect(self._on_double_clicked)
        self.table.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    # Наповнення
    # ------------------------------------------------------------------

    def set_lessons(self, lessons: list[LessonInfo], read_only: bool) -> None:
        """Перебудовує список (єдина точка оновлення); виділений урок зберігається, якщо він ще є."""
        self._lessons = list(lessons)
        self._read_only = read_only
        self._populate()

    def refresh_theme(self) -> None:
        """Перемальовує кольори рядків після зміни теми."""
        self._populate()

    def _populate(self) -> None:
        table = self.table
        table.blockSignals(True)
        table.setRowCount(len(self._lessons))
        muted = QBrush(QColor(theme.color("muted")))
        for row, lesson in enumerate(self._lessons):
            text = lesson_row_text(lesson)
            placeholder = lesson.lesson_type == "regular" and not lesson.topic
            items = (
                QTableWidgetItem(str(row + 1)),
                QTableWidgetItem(f"{lesson.lesson_date:%d.%m}"),
                QTableWidgetItem(NO_TOPIC_TEXT if placeholder else text),
            )
            tint = _TINT.get(lesson.lesson_type)
            for column, item in enumerate(items):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if column < 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if tint:
                    item.setBackground(QColor(theme.color(tint)))
                item.setToolTip(
                    f"Урок № {row + 1} · {lesson.lesson_date:%d.%m.%Y}\n{NO_TOPIC_TEXT if placeholder else text}"
                )
                table.setItem(row, column, item)
            if placeholder:
                font = items[2].font()
                font.setItalic(True)
                items[2].setFont(font)
                items[2].setForeground(muted)
        table.blockSignals(False)
        self._fit_rows()
        QTimer.singleShot(0, self._fit_rows)  # ширина стовпця «Тема» остаточна лише після розкладки
        self.select_lesson(self._selected_id)

    def _fit_rows(self) -> None:
        """Висота рядків за перенесеним текстом (залежить від ширини стовпця «Тема»)."""
        self.table.resizeRowsToContents()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_rows()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_rows()

    # ------------------------------------------------------------------
    # Виділення
    # ------------------------------------------------------------------

    def row_of(self, lesson_id: int) -> int:
        return next((i for i, lesson in enumerate(self._lessons) if lesson.id == lesson_id), -1)

    def select_lesson(self, lesson_id: int | None) -> None:
        """Підсвічує рядок уроку й прокручує до нього; сигналів не надсилає."""
        self._selected_id = lesson_id
        row = self.row_of(lesson_id) if lesson_id is not None else -1
        self.table.blockSignals(True)
        if row < 0:
            self.table.clearSelection()
        else:
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 2))
        self.table.blockSignals(False)

    def selected_lesson_id(self) -> int | None:
        return self._selected_id if self.row_of(self._selected_id or -1) >= 0 else None

    # ------------------------------------------------------------------
    # Дії користувача
    # ------------------------------------------------------------------

    def _on_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._lessons):
            lesson_id = self._lessons[row].id
            self._selected_id = lesson_id
            self.lesson_selected.emit(lesson_id)

    def _on_double_clicked(self, row: int, _column: int) -> None:
        if not self._read_only and 0 <= row < len(self._lessons):
            self.lesson_edit_requested.emit(self._lessons[row].id)

    def _on_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if self._read_only or not 0 <= row < len(self._lessons):
            return
        lesson_id = self._lessons[row].id
        menu = QMenu(self)
        edit = menu.addAction("Редагувати урок")
        delete = menu.addAction("Видалити урок")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is edit:
            self.lesson_edit_requested.emit(lesson_id)
        elif chosen is delete:
            self.lesson_delete_requested.emit(lesson_id)

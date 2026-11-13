"""Панель «Проведені уроки»: №, дата, тема й домашнє завдання поруч із таблицею журналу.

№ — наскрізний номер уроку за навчальний рік (LessonInfo.number). Між уроками стоять приглушені
рядки-роздільники «Тематична» / «Зошит» (без № і дати). Єдине, що панель редагує сама, — «Д/з»
(поле на місці за подвійним кліком); решту вона просить сторінку сигналами.
Усі кольори беруться з journal.ui.theme (theme.color) у момент наповнення.
"""
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from journal.services.journal_types import MAX_HOMEWORK, ExtraColumnInfo, LessonInfo
from journal.ui import theme
from journal.ui.journal_dialogs import EXTRA_COLUMN_TYPES, LESSON_TYPES

NUMBER_WIDTH = 36
DATE_WIDTH = 56
HOMEWORK_WIDTH = 110
TOPIC_COL = 2
HOMEWORK_COL = 3
NO_TOPIC_TEXT = "тема не вказана"
HOMEWORK_HINT = "Подвійний клік — змінити домашнє завдання"
TEXT_PADDING = 4  # відступ усередині клітинки (як у QSS панелі)
TEXT_SLACK = 10   # запас по ширині на переноси й межу клітинки

# Тло рядка за типом уроку (звичайний урок — без тла)
_TINT = {
    "test": "lesson_test_soft",
    "lab": "lesson_lab_soft",
    "independent": "lesson_independent_soft",
    "quiz": "lesson_quiz_soft",
    "project": "lesson_project_soft",
}
_SEPARATOR_ROLE = Qt.ItemDataRole.UserRole + 1  # True у клітинках рядка-роздільника
# Порядок стовпчиків без дати при однаковій даті: уроки → «Зошит» → «Тематична»
_KIND_ORDER = {"notebook": 0, "thematic": 1}


def lesson_row_text(lesson: LessonInfo) -> str:
    """Текст стовпця «Тема»: для звичайного уроку — тема (або порожньо), для решти — «Тип: тема»."""
    topic = lesson.topic or ""
    if lesson.lesson_type == "regular":
        return topic
    name = LESSON_TYPES[lesson.lesson_type][0]
    return f"{name}: {topic}" if topic else name


def merge_rows(
    lessons: list[LessonInfo], extra_columns: list[ExtraColumnInfo]
) -> list[LessonInfo | ExtraColumnInfo]:
    """Уроки й стовпчики без дати в порядку таблиці: стовпчик стоїть після кожного уроку з датою ≤ after_date."""
    pending = sorted(extra_columns, key=lambda c: (c.after_date, _KIND_ORDER.get(c.kind, 9), c.id))
    merged: list[LessonInfo | ExtraColumnInfo] = []
    for lesson in lessons:
        while pending and pending[0].after_date < lesson.lesson_date:
            merged.append(pending.pop(0))
        merged.append(lesson)
    merged.extend(pending)
    return merged


class _TintDelegate(QStyledItemDelegate):
    """Малює тло рядка за типом уроку (стилі теми інакше ігнорують колір елемента); «Д/з» — в один рядок."""

    def paint(self, painter, option, index) -> None:
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is not None and not option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, brush)
        if index.column() == HOMEWORK_COL:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.features &= ~QStyleOptionViewItem.ViewItemFeature.WrapText
            opt.textElideMode = Qt.TextElideMode.ElideRight
            widget = option.widget
            style = widget.style() if widget is not None else None
            if style is not None:
                style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
                return
        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        """Висота за реальною шириною стовпця (з запасом на відступи), щоб текст не обрізався трьома крапками."""
        hint = super().sizeHint(option, index)
        line = option.fontMetrics.height() + 2 * TEXT_PADDING + 4
        if index.data(_SEPARATOR_ROLE) or index.column() == HOMEWORK_COL:
            hint.setHeight(line)  # роздільник і «Д/з» — завжди в один рядок
            return hint
        if index.column() != TOPIC_COL:
            return hint
        width = self.parent().columnWidth(TOPIC_COL) - 2 * TEXT_PADDING - TEXT_SLACK
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft)
        rect = option.fontMetrics.boundingRect(0, 0, max(width, 20), 10000, flags, index.data() or "")
        hint.setHeight(max(rect.height() + 2 * TEXT_PADDING + 4, line))
        return hint


class _HomeworkEdit(QLineEdit):
    """Поле «Д/з» на місці: Enter або втрата фокусу — зберегти, Esc — скасувати.

    Втрата фокусу ЗБЕРІГАЄ текст (як у таблицях): клік деінде посеред уроку не має
    губити введене домашнє завдання.
    """

    cancelled = Signal()
    committed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.committed.emit()


class LessonPanel(QWidget):
    """Список проведених уроків семестру з наскрізними номерами, роздільниками стовпчиків і «Д/з»."""

    lesson_selected = Signal(int)          # клік по рядку
    lesson_edit_requested = Signal(int)    # подвійний клік / меню
    lesson_delete_requested = Signal(int)  # меню
    homework_edited = Signal(int, str)     # (id уроку, новий текст д/з) — Enter у полі «Д/з»
    column_move_requested = Signal(int)    # (id стовпчика) — меню роздільника
    column_delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LessonPanel")
        self._rows: list[LessonInfo | ExtraColumnInfo] = []
        self._lessons: list[LessonInfo] = []
        self._read_only = False
        self._selected_id: int | None = None
        self._editor: _HomeworkEdit | None = None
        self._editor_row = -1

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

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("LessonTable")
        self.table.setHorizontalHeaderLabels(["№", "Дата", "Тема", "Д/з"])
        for column in (TOPIC_COL, HOMEWORK_COL):
            self.table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(TOPIC_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(HOMEWORK_COL, QHeaderView.ResizeMode.Interactive)
        header.setHighlightSections(False)
        self.table.setColumnWidth(0, NUMBER_WIDTH)
        self.table.setColumnWidth(1, DATE_WIDTH)
        self.table.setColumnWidth(HOMEWORK_COL, HOMEWORK_WIDTH)
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

    def set_items(self, lessons: list[LessonInfo], extra_columns: list[ExtraColumnInfo], read_only: bool) -> None:
        """Перебудовує список (єдина точка оновлення); виділений урок зберігається, якщо він ще є."""
        self._lessons = list(lessons)
        self._rows = merge_rows(self._lessons, list(extra_columns))
        self._read_only = read_only
        self._populate()

    def set_lessons(self, lessons: list[LessonInfo], read_only: bool) -> None:
        """Сумісність зі старою сторінкою: лише уроки, без стовпчиків."""
        self.set_items(lessons, [], read_only)

    def refresh_theme(self) -> None:
        """Перемальовує кольори рядків після зміни теми."""
        self._populate()

    def _populate(self) -> None:
        self._drop_editor()
        table = self.table
        table.blockSignals(True)
        table.clearSpans()
        table.setRowCount(0)
        table.setRowCount(len(self._rows))
        muted = QBrush(QColor(theme.color("muted")))
        position = 0  # запасний номер, якщо сервіс не заповнив LessonInfo.number
        for row, entry in enumerate(self._rows):
            if isinstance(entry, LessonInfo):
                position += 1
                self._fill_lesson_row(row, entry, entry.number or position, muted)
            else:
                self._fill_separator_row(row, entry, muted)
        table.blockSignals(False)
        self._fit_rows()
        QTimer.singleShot(0, self._fit_rows)  # ширина стовпця «Тема» остаточна лише після розкладки
        self.select_lesson(self._selected_id)

    def _fill_lesson_row(self, row: int, lesson: LessonInfo, number: int, muted: QBrush) -> None:
        text = lesson_row_text(lesson)
        placeholder = lesson.lesson_type == "regular" and not lesson.topic
        homework = lesson.homework or ""
        items = (
            QTableWidgetItem(str(number)),
            QTableWidgetItem(f"{lesson.lesson_date:%d.%m}"),
            QTableWidgetItem(NO_TOPIC_TEXT if placeholder else text),
            QTableWidgetItem(homework),
        )
        tint = _TINT.get(lesson.lesson_type)
        for column, item in enumerate(items):
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if column < TOPIC_COL:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if tint:
                item.setBackground(QColor(theme.color(tint)))
            tip = f"Урок № {number} · {lesson.lesson_date:%d.%m.%Y}\n{NO_TOPIC_TEXT if placeholder else text}"
            if column == HOMEWORK_COL:
                tip = f"Д/з: {homework}" if homework else HOMEWORK_HINT
            item.setToolTip(tip)
            self.table.setItem(row, column, item)
        if placeholder:
            font = items[TOPIC_COL].font()
            font.setItalic(True)
            items[TOPIC_COL].setFont(font)
            items[TOPIC_COL].setForeground(muted)

    def _fill_separator_row(self, row: int, column: ExtraColumnInfo, muted: QBrush) -> None:
        name = EXTRA_COLUMN_TYPES[column.kind][0]
        tint = {"thematic": "col_thematic_soft", "notebook": "col_notebook_soft"}.get(column.kind)
        tip = f"{name} {column.ordinal}" + ("" if self._read_only else "\nПравий клік — перемістити або видалити")
        for index in range(4):
            item = QTableWidgetItem(name if index == 0 else "")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # без виділення й без № та дати
            item.setData(_SEPARATOR_ROLE, True)
            item.setForeground(muted)
            item.setToolTip(tip)
            if tint:
                item.setBackground(QColor(theme.color(tint)))
            self.table.setItem(row, index, item)
        self.table.setSpan(row, 0, 1, 4)

    def _fit_rows(self) -> None:
        """Висота рядків за перенесеним текстом (залежить від ширини стовпця «Тема»)."""
        self.table.resizeRowsToContents()
        if self._editor is not None:
            self._place_editor()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_rows()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_rows()

    # ------------------------------------------------------------------
    # Виділення
    # ------------------------------------------------------------------

    def _entry_at(self, row: int) -> LessonInfo | ExtraColumnInfo | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def row_of(self, lesson_id: int) -> int:
        return next(
            (i for i, e in enumerate(self._rows) if isinstance(e, LessonInfo) and e.id == lesson_id), -1
        )

    def select_lesson(self, lesson_id: int | None) -> None:
        """Підсвічує рядок уроку й прокручує до нього; сигналів не надсилає."""
        self._selected_id = lesson_id
        row = self.row_of(lesson_id) if lesson_id is not None else -1
        self.table.blockSignals(True)
        if row < 0:
            self.table.clearSelection()
        else:
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, TOPIC_COL))
        self.table.blockSignals(False)

    def selected_lesson_id(self) -> int | None:
        return self._selected_id if self.row_of(self._selected_id or -1) >= 0 else None

    # ------------------------------------------------------------------
    # Домашнє завдання: редагування на місці
    # ------------------------------------------------------------------

    def start_homework_edit(self, row: int) -> bool:
        """Відкриває поле «Д/з» у рядку уроку. False — рядок не урок або панель лише для читання."""
        entry = self._entry_at(row)
        if self._read_only or not isinstance(entry, LessonInfo):
            return False
        self._drop_editor()
        editor = _HomeworkEdit(self.table.viewport())
        editor.setMaxLength(MAX_HOMEWORK)
        editor.setText(entry.homework or "")
        editor.setPlaceholderText("домашнє завдання")
        editor.returnPressed.connect(self._commit_editor)
        editor.cancelled.connect(self._cancel_editor)
        editor.committed.connect(self._commit_editor)
        self._editor, self._editor_row = editor, row
        self._place_editor()
        editor.show()
        editor.setFocus()
        editor.selectAll()
        return True

    def _place_editor(self) -> None:
        if self._editor is None:
            return
        rect = self.table.visualRect(self.table.model().index(self._editor_row, HOMEWORK_COL))
        self._editor.setGeometry(rect)

    def _drop_editor(self) -> None:
        editor, self._editor, self._editor_row = self._editor, None, -1
        if editor is not None:
            editor.hide()
            editor.deleteLater()

    def _cancel_editor(self) -> None:
        self._drop_editor()

    def _commit_editor(self) -> None:
        editor, row = self._editor, self._editor_row
        entry = self._entry_at(row)
        if editor is None or not isinstance(entry, LessonInfo):
            self._drop_editor()
            return
        text = editor.text().strip()
        self._drop_editor()
        if text != (entry.homework or "").strip():
            self.homework_edited.emit(entry.id, text)

    def homework_editor(self) -> QLineEdit | None:
        """Поле «Д/з», що зараз відкрите (для тестів і сторінки)."""
        return self._editor

    # ------------------------------------------------------------------
    # Дії користувача
    # ------------------------------------------------------------------

    def _on_clicked(self, row: int, _column: int) -> None:
        entry = self._entry_at(row)
        if isinstance(entry, LessonInfo):
            self._selected_id = entry.id
            self.lesson_selected.emit(entry.id)

    def _on_double_clicked(self, row: int, column: int) -> None:
        entry = self._entry_at(row)
        if self._read_only or not isinstance(entry, LessonInfo):
            return
        if column == HOMEWORK_COL:
            self.start_homework_edit(row)
        else:
            self.lesson_edit_requested.emit(entry.id)

    def _on_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        entry = self._entry_at(row)
        if self._read_only or entry is None:
            return
        menu = QMenu(self)
        if isinstance(entry, LessonInfo):
            edit = menu.addAction("Редагувати урок")
            delete = menu.addAction("Видалити урок")
            move = None
        else:
            move = menu.addAction("Перемістити…")
            delete = menu.addAction("Видалити")
            edit = None
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if isinstance(entry, LessonInfo):
            if chosen is edit:
                self.lesson_edit_requested.emit(entry.id)
            elif chosen is delete:
                self.lesson_delete_requested.emit(entry.id)
        elif chosen is move:
            self.column_move_requested.emit(entry.id)
        elif chosen is delete:
            self.column_delete_requested.emit(entry.id)

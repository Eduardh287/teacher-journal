"""Таблиця журналу: модель, заголовок стовпців, делегат малювання клітинок і сам вигляд з клавіатурою.

Усі кольори беруться з journal.ui.theme (theme.color) у момент малювання, тож тема перемикається «на льоту».
Вигляд не звертається до сервісу напряму: збереження клітинки виконує функція `saver`, яку задає сторінка.
"""
from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from journal.services.class_service import StudentInfo
from journal.services.grid_text import (  # noqa: F401 (cell_text, computed_text — публічні імена модуля)
    EXTRA_COLUMN_TYPES,
    FINAL_COLUMN_TITLES,
    LESSON_TYPES,
    NA_TEXT,
    cell_text,
    computed_text,
)
from journal.services.journal_types import (
    AttendanceCode,
    CellInfo,
    ComputedCell,
    ComputedKey,
    ExtraColumnInfo,
    GridColumn,
    GridData,
    LessonInfo,
)
from journal.ui import theme
from journal.ui.journal_dialogs import CommentDialog

GRADE_CHAIN_MS = 500  # скільки чекаємо другу цифру після «1» (10/11/12)
COLUMN_WIDTH = 56
NAME_WIDTH = 240
ROW_HEIGHT = 34
HEADER_HEIGHT = 46

LessonRole = Qt.ItemDataRole.UserRole + 1   # LessonInfo заголовка стовпця
CellRole = Qt.ItemDataRole.UserRole + 2     # CellInfo клітинки
PendingRole = Qt.ItemDataRole.UserRole + 3  # True, якщо в клітинці очікує друга цифра
StudentRole = Qt.ItemDataRole.UserRole + 4  # StudentInfo заголовка рядка
ComputedRole = Qt.ItemDataRole.UserRole + 5  # ComputedCell клітинки (або None) — етап 6
ColumnRole = Qt.ItemDataRole.UserRole + 6    # GridColumn заголовка стовпця
ExtraRole = Qt.ItemDataRole.UserRole + 7     # ExtraColumnInfo заголовка (для «Тем»/«Зош») або None

EMPTY_CELL = CellInfo("present", None, None)

# Клавіші позначок за event.text() (латиниця — для розкладки без українських літер)
ABSENT_KEYS = ("н", "y")
SICK_KEYS = ("х", "[")
LATE_KEYS = ("з", "p")

# Тло заголовка за типом уроку (None — звичайне)
_LESSON_TINT = {
    "test": "lesson_test_soft",
    "lab": "lesson_lab_soft",
    "independent": "lesson_independent_soft",
    "quiz": "lesson_quiz_soft",
    "project": "lesson_project_soft",
}
# Тло стовпців без дати (заголовок і клітинки)
_COLUMN_TINT = {
    "thematic": "col_thematic_soft",
    "notebook": "col_notebook_soft",
    "semester": "col_final_soft",
    "annual": "col_final_soft",
}

SaveCell = Callable[[int, int, AttendanceCode, "int | None", "str | None"], "tuple[bool, CellInfo | None]"]
SaveOverride = Callable[[int, ComputedKey, "int | None", bool], "tuple[bool, dict[ComputedKey, ComputedCell] | None]"]


def grades_text(n: int) -> str:
    """«1 оцінка», «2 оцінки», «5 оцінок»."""
    if n % 100 in (11, 12, 13, 14):
        word = "оцінок"
    elif n % 10 == 1:
        word = "оцінка"
    elif n % 10 in (2, 3, 4):
        word = "оцінки"
    else:
        word = "оцінок"
    return f"{n} {word}"


def _mean_text(total: int, count: int) -> str:
    return f"{total / count:.2f}".replace(".", ",") if count else "—"


def computed_tooltip(kind: str, cell: ComputedCell | None) -> str | None:
    """Підказка до клітинки тематичної / зошита / семестрової / річної."""
    if kind == "notebook":
        return "Оцінка за зошит — не враховується в середніх"
    if cell is None:
        return None
    if cell.is_manual:
        shown = NA_TEXT if cell.override_na else str(cell.override)
        auto = NA_TEXT if cell.auto_na or cell.auto is None else str(cell.auto)
        text = f"Виставлено вручну: {shown}"
        if cell.override_na:
            text += " (у розрахунках н/а = 0)"
        return f"{text}\nАвтоматично: {auto}. Del — повернути автоматичне значення"
    if kind == "thematic":
        if cell.auto_na:
            return "н/а — немає оцінок за тему"
        return f"Середнє {_mean_text(cell.total, cell.count)} ({grades_text(cell.count)}) → {cell.auto}"
    if kind == "semester":
        if cell.auto_na:
            if cell.count == 0:
                return "н/а — немає тематичних оцінок"
            return "н/а — усі тематичні н/а (н/а = 0)"
        return f"Середнє тематичних {_mean_text(cell.total, cell.count)} (н/а = 0) → {cell.auto}"
    if cell.auto_na:
        return "н/а — немає семестрових оцінок"
    return (
        f"Середнє двох семестрових {_mean_text(cell.total, 2)} → {cell.auto}\n"
        "Відсутня чи н/а семестрова рахується як 0"
    )


def header_text(lesson: LessonInfo) -> str:
    """Текст заголовка стовпця: «12.11» і, для не звичайних уроків, абревіатура другим рядком."""
    abbr = LESSON_TYPES[lesson.lesson_type][1]
    day = f"{lesson.lesson_date:%d.%m}"
    return f"{day}\n{abbr}" if abbr else day


class JournalGridModel(QAbstractTableModel):
    """Рядки — учні, стовпці — уроки, «Тем»/«Зош» і підсумкові. Змінюється лише після успішного збереження."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.students: list[StudentInfo] = []
        self.lessons: list[LessonInfo] = []
        self.columns: list[GridColumn] = []
        self.extras: dict[int, ExtraColumnInfo] = {}
        self.semester = 1
        self.cells: dict[tuple[int, int], CellInfo] = {}
        self.computed: dict[tuple[int, ComputedKey], ComputedCell] = {}
        self.read_only = False
        self.pending: tuple[int, int] | None = None  # (рядок, стовпець) із очікуваною «1»

    def set_grid(self, grid: GridData) -> None:
        self.beginResetModel()
        self.students = list(grid.students)
        self.lessons = list(grid.lessons)
        self.columns = list(grid.columns) or [GridColumn("lesson", lesson.id) for lesson in grid.lessons]
        self.extras = {e.id: e for e in grid.extra_columns}
        self.semester = grid.semester
        self.cells = dict(grid.cells)
        self.computed = dict(grid.computed)
        # Архівний журнал редагується (рішення автора); лише рядки вибулих учнів — для перегляду.
        self.read_only = False
        self.pending = None
        self.endResetModel()

    # --- доступ ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.students)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def kind_at(self, column: int) -> str:
        return self.columns[column].kind

    def lesson_at(self, column: int) -> LessonInfo | None:
        """Урок стовпця (None для «Тем»/«Зош»/підсумкових)."""
        if not 0 <= column < len(self.columns) or self.columns[column].kind != "lesson":
            return None
        return next((x for x in self.lessons if x.id == self.columns[column].id), None)

    def computed_key(self, column: int) -> ComputedKey | None:
        col = self.columns[column]
        if col.kind == "lesson":
            return None
        if col.kind == "semester":
            return ("semester", self.semester)
        if col.kind == "annual":
            return ("annual", 0)
        return (col.kind, col.id)

    def computed_cell(self, row: int, column: int) -> ComputedCell | None:
        key = self.computed_key(column)
        return None if key is None else self.computed.get((self.students[row].id, key))

    def cell(self, row: int, column: int) -> CellInfo:
        lesson = self.lesson_at(column)
        if lesson is None:
            return EMPTY_CELL
        return self.cells.get((self.students[row].id, lesson.id), EMPTY_CELL)

    def apply_computed(
        self, student_id: int, result: dict[ComputedKey, ComputedCell] | None, edited: ComputedKey | None = None
    ) -> None:
        """Підставляє обчислювані клітинки учня, які повернув сервіс; edited — ключ, що міг зникнути."""
        if edited is not None:
            self.computed.pop((student_id, edited), None)
        for key, cell in (result or {}).items():
            self.computed[(student_id, key)] = cell
        row = next((i for i, s in enumerate(self.students) if s.id == student_id), -1)
        if row >= 0 and self.columns:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.columns) - 1))

    def is_editable(self, row: int) -> bool:
        return not self.read_only and not self.students[row].archived

    def column_of(self, lesson_id: int) -> int:
        return next((i for i, c in enumerate(self.columns) if c.kind == "lesson" and c.id == lesson_id), -1)

    def column_index(self, column: GridColumn) -> int:
        return next((i for i, c in enumerate(self.columns) if c == column), -1)

    def apply_cell(self, row: int, column: int, cell: CellInfo | None) -> None:
        """Записує в модель те, що повернув сервіс (None = клітинка порожня)."""
        lesson = self.lesson_at(column)
        if lesson is None:
            return
        key = (self.students[row].id, lesson.id)
        if cell is None:
            self.cells.pop(key, None)
        else:
            self.cells[key] = cell
        index = self.index(row, column)
        self.dataChanged.emit(index, index)

    def set_pending(self, pending: tuple[int, int] | None) -> None:
        old, self.pending = self.pending, pending
        for ref in (old, pending):
            if ref is not None:
                index = self.index(*ref)
                self.dataChanged.emit(index, index)

    # --- дані ---

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role == PendingRole:
            return self.pending == (row, column)
        if role == CellRole:
            return self.cell(row, column)
        kind = self.kind_at(column)
        if role == ComputedRole:
            return self.computed_cell(row, column)
        if role == Qt.ItemDataRole.DisplayRole:
            if self.pending == (row, column):
                return "1"
            if kind != "lesson":
                return computed_text(kind, self.computed_cell(row, column))
            return cell_text(self.cell(row, column))
        if role == Qt.ItemDataRole.ToolTipRole:
            if kind != "lesson":
                return computed_tooltip(kind, self.computed_cell(row, column))
            return self.cell(row, column).comment
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if not 0 <= section < len(self.columns):
                return None
            column = self.columns[section]
            if role == ColumnRole:
                return column
            if column.kind != "lesson":
                extra = self.extras.get(column.id) if column.id is not None else None
                if role == ExtraRole:
                    return extra
                if role == Qt.ItemDataRole.DisplayRole:
                    if column.kind in FINAL_COLUMN_TITLES:
                        return FINAL_COLUMN_TITLES[column.kind][1]
                    abbr = EXTRA_COLUMN_TYPES[column.kind][1]
                    return f"{abbr}\n{extra.ordinal}" if extra else abbr
                if role == Qt.ItemDataRole.ToolTipRole:
                    return _column_tooltip(column.kind, extra)
                return None
            lesson = self.lesson_at(section)
            if lesson is None:
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                return header_text(lesson)
            if role == LessonRole:
                return lesson
            if role == Qt.ItemDataRole.ToolTipRole:
                name = LESSON_TYPES[lesson.lesson_type][0]
                number = lesson.number or self.lessons.index(lesson) + 1
                text = f"Урок № {number} · {lesson.lesson_date:%d.%m.%Y} · {name}"
                text = f"{text}\n{lesson.topic}" if lesson.topic else text
                return f"{text}\nДомашнє завдання: {lesson.homework}" if lesson.homework else text
            return None
        if not 0 <= section < len(self.students):
            return None
        student = self.students[section]
        if role == Qt.ItemDataRole.DisplayRole:
            # Вибулі учні не мають номера в журналі (position = 0).
            if student.archived:
                return f"вибув · {student.full_name}"
            return f"{student.position}. {student.full_name}"
        if role == StudentRole:
            return student
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and student.archived:
            return QColor(theme.color("muted"))
        if role == Qt.ItemDataRole.ToolTipRole:
            if student.archived:
                return f"{student.full_name}\nУчень вибув — лише перегляд"
            return student.full_name
        return None


def _column_tooltip(kind: str, extra: ExtraColumnInfo | None) -> str:
    n = f" № {extra.ordinal}" if extra else ""
    if kind == "thematic":
        return f"Тематична{n} — середнє оцінок за тему, можна виставити вручну"
    if kind == "notebook":
        return f"Зошит{n} — оцінка за зошит, не враховується в середніх"
    if kind == "semester":
        return "Семестрова — середнє тематичних оцінок"
    return "Річна — середнє двох семестрових оцінок"


class JournalHeaderView(QHeaderView):
    """Горизонтальний заголовок: дата й абревіатура типу уроку на тлі, що залежить від типу."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setDefaultSectionSize(COLUMN_WIDTH)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        if not rect.isValid():
            return
        model = self.model()
        lesson = model.headerData(logical_index, Qt.Orientation.Horizontal, LessonRole)
        column: GridColumn | None = model.headerData(logical_index, Qt.Orientation.Horizontal, ColumnRole)
        painter.save()
        if lesson:
            token = _LESSON_TINT.get(lesson.lesson_type)
        else:
            token = _COLUMN_TINT.get(column.kind) if column else None
        painter.fillRect(rect, QColor(theme.color(token or "surface")))
        painter.setPen(QPen(QColor(theme.color("border"))))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())
        if column is not None and column.kind == "semester":
            painter.setPen(QPen(QColor(theme.color("muted")), 2))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        if column is not None and column.kind in ("thematic", "notebook"):
            extra: ExtraColumnInfo | None = model.headerData(logical_index, Qt.Orientation.Horizontal, ExtraRole)
            font = QFont(painter.font())
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(theme.color("text")))
            painter.drawText(
                QRect(rect.x(), rect.y() + 6, rect.width(), 18), Qt.AlignmentFlag.AlignCenter,
                EXTRA_COLUMN_TYPES[column.kind][1],
            )
            if extra:
                font.setBold(False)
                font.setPointSize(8)
                painter.setFont(font)
                painter.setPen(QColor(theme.color("muted")))
                painter.drawText(
                    QRect(rect.x(), rect.y() + 24, rect.width(), 16), Qt.AlignmentFlag.AlignCenter, str(extra.ordinal)
                )
        elif column is not None and column.kind in FINAL_COLUMN_TITLES:
            font = QFont(painter.font())
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(theme.color("text")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, FINAL_COLUMN_TITLES[column.kind][1])
        if lesson:
            abbr = LESSON_TYPES[lesson.lesson_type][1]
            top = QRect(rect.x(), rect.y() + 6, rect.width(), 18)
            bottom = QRect(rect.x(), rect.y() + 24, rect.width(), 16)
            font = QFont(painter.font())
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(theme.color("text")))
            painter.drawText(top, Qt.AlignmentFlag.AlignCenter, f"{lesson.lesson_date:%d.%m}")
            if abbr:
                font.setBold(False)
                font.setPointSize(8)
                painter.setFont(font)
                painter.setPen(QColor(theme.color("muted")))
                painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, abbr)
        painter.restore()


class JournalCellDelegate(QStyledItemDelegate):
    """Малює клітинку: тло за позначкою, текст, виділення і трикутник коментаря."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        cell: CellInfo = index.data(CellRole)
        model: JournalGridModel = index.model()
        row = index.row()
        rect = option.rect
        muted_row = model.students[row].archived
        kind = model.kind_at(index.column())
        computed: ComputedCell | None = index.data(ComputedRole)
        painter.save()

        soft = {"absent": "mark_absent_soft", "sick": "mark_sick_soft", "late": "mark_late_soft"}.get(cell.attendance)
        if muted_row:
            painter.fillRect(rect, QColor(theme.color("hover")))
        elif kind != "lesson":
            painter.fillRect(rect, QColor(theme.color(_COLUMN_TINT[kind])))
        elif soft:
            painter.fillRect(rect, QColor(theme.color(soft)))
        else:
            painter.fillRect(rect, QColor(theme.color("surface")))

        # сітка
        painter.setPen(QPen(QColor(theme.color("border"))))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())
        if kind == "semester":  # жирний роздільник перед підсумковими стовпцями
            painter.setPen(QPen(QColor(theme.color("muted")), 2))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())

        # текст
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            pending = index.data(PendingRole)
            if kind == "lesson":
                color_token = {"absent": "mark_absent", "sick": "mark_sick", "late": "mark_late"}.get(
                    cell.attendance, "text"
                )
                bold = not pending
                manual = False
            else:
                color_token = "text"
                # авто — звичайна вага; ручне — жирний + акцентне підкреслення; «Зош» — сама оцінка
                manual = bool(computed and computed.is_manual and kind != "notebook")
                bold = manual or kind == "notebook"
                if computed is not None and computed.is_na and not computed.is_manual:
                    color_token = "muted"
            if muted_row or pending:
                color_token = "muted"
            font = QFont(painter.font())
            font.setBold(bold and not pending)
            font.setItalic(bool(pending))
            painter.setFont(font)
            painter.setPen(QColor(theme.color(color_token)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if manual and not pending:
                metrics = QFontMetrics(font)
                width = metrics.horizontalAdvance(text)
                y = rect.center().y() + metrics.ascent() // 2 + 3
                painter.setPen(QPen(QColor(theme.color("accent")), 2))
                painter.drawLine(rect.center().x() - width // 2, y, rect.center().x() + (width + 1) // 2, y)

        # трикутник коментаря в правому верхньому куті
        if kind == "lesson" and cell.comment:
            size = 10
            triangle = QPolygon(
                [
                    QPoint(rect.right() - size, rect.top() + 1),
                    QPoint(rect.right() - 1, rect.top() + 1),
                    QPoint(rect.right() - 1, rect.top() + size),
                ]
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.color("accent")))
            painter.drawPolygon(triangle)

        # виділена клітинка — рамка акцентного кольору
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.color("accent")), 2))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        painter.restore()


class JournalGridView(QTableView):
    """Таблиця журналу з усією клавіатурною логікою введення (специфікація етапу 5, §4–5)."""

    lesson_edit_requested = Signal(int)    # id уроку (подвійний клік / меню)
    lesson_delete_requested = Signal(int)
    column_move_requested = Signal(int)    # id extra-стовпчика («Тем»/«Зош»)
    column_delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.saver: SaveCell | None = None
        self.override_saver: SaveOverride | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush_pending)
        self.grid_model = JournalGridModel(self)
        self.setModel(self.grid_model)

        self.setHorizontalHeader(JournalHeaderView(self))
        vheader = self.verticalHeader()
        vheader.setDefaultSectionSize(ROW_HEIGHT)
        vheader.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vheader.setFixedWidth(NAME_WIDTH)
        vheader.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vheader.setHighlightSections(False)
        vheader.setTextElideMode(Qt.TextElideMode.ElideRight)

        self.setItemDelegate(JournalCellDelegate(self))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTabKeyNavigation(False)

        header = self.horizontalHeader()
        header.sectionDoubleClicked.connect(self._on_header_double_click)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_menu)

    # ------------------------------------------------------------------
    # Службове
    # ------------------------------------------------------------------

    def set_grid(self, grid: GridData) -> None:
        self._stop_pending()
        self.grid_model.set_grid(grid)
        for column in range(self.grid_model.columnCount()):
            self.setColumnWidth(column, COLUMN_WIDTH)

    def select_cell(self, row: int, column: int) -> None:
        if 0 <= row < self.grid_model.rowCount() and 0 <= column < self.grid_model.columnCount():
            self.setCurrentIndex(self.grid_model.index(row, column))

    def focusNextPrevChild(self, next_: bool) -> bool:  # noqa: FBT001
        return False  # Tab/Shift+Tab обробляємо самі, як рух по клітинках

    def _ref(self) -> tuple[int, int] | None:
        index = self.currentIndex()
        return (index.row(), index.column()) if index.isValid() else None

    def _stop_pending(self) -> None:
        self._timer.stop()
        if self.grid_model.pending is not None and self.grid_model.rowCount():
            self.grid_model.set_pending(None)
        else:
            self.grid_model.pending = None

    # ------------------------------------------------------------------
    # Збереження
    # ------------------------------------------------------------------

    def _save(self, row: int, column: int, attendance: AttendanceCode, grade: int | None, comment: str | None) -> None:
        """Одне звернення до saver; модель змінюється лише після успіху."""
        old = self.grid_model.cell(row, column)
        comment = (comment or "").strip() or None
        if CellInfo(attendance, grade, comment) == old or self.saver is None:
            return
        student_id = self.grid_model.students[row].id
        lesson = self.grid_model.lesson_at(column)
        if lesson is None:
            return
        lesson_id = lesson.id
        ok, result = self.saver(student_id, lesson_id, attendance, grade, comment)
        if ok:
            self.grid_model.apply_cell(row, column, result)

    def _save_override(self, row: int, column: int, grade: int | None, na: bool = False) -> None:
        """Ручна оцінка / н/а / очищення в обчислюваній клітинці (або оцінка «Зошита»)."""
        model = self.grid_model
        key = model.computed_key(column)
        if key is None or self.override_saver is None:
            return
        old = model.computed_cell(row, column)
        if grade is not None:
            if old is not None and old.override == grade and not old.override_na:
                return
        elif na:
            if old is not None and old.override_na:
                return
        elif old is None or not old.is_manual:
            return
        student_id = model.students[row].id
        ok, result = self.override_saver(student_id, key, grade, na)
        if ok:
            model.apply_computed(student_id, result, edited=key)

    def _set_grade(self, row: int, column: int, grade: int) -> None:
        if self.grid_model.kind_at(column) != "lesson":
            self._save_override(row, column, grade)
            return
        old = self.grid_model.cell(row, column)
        attendance = "present" if old.attendance in ("absent", "sick") else old.attendance
        self._save(row, column, attendance, grade, old.comment)

    def flush_pending(self) -> None:
        """Підтверджує відкладену «1» як оцінку 1 (таймер, зміна клітинки, втрата фокуса, семестр)."""
        self._timer.stop()
        pending = self.grid_model.pending
        if pending is None:
            return
        self.grid_model.set_pending(None)
        self._set_grade(*pending, 1)

    def _grade_key(self, digit: int, row: int, column: int) -> None:
        pending = self.grid_model.pending
        if pending == (row, column) and digit in (0, 1, 2):
            self._timer.stop()
            self.grid_model.set_pending(None)
            self._set_grade(row, column, 10 + digit)
        elif digit == 1:
            self.grid_model.set_pending((row, column))
            self._timer.start(GRADE_CHAIN_MS)
        elif digit >= 2:
            self._set_grade(row, column, digit)

    def _mark_key(self, mark: AttendanceCode, row: int, column: int) -> None:
        old = self.grid_model.cell(row, column)
        if old.attendance == mark:
            self._save(row, column, "present", old.grade, old.comment)
        elif mark == "late":
            self._save(row, column, "late", old.grade, old.comment)
        else:
            self._save(row, column, mark, None, old.comment)

    def edit_comment(self) -> None:
        """F2: діалог коментаря до поточної клітинки."""
        ref = self._ref()
        if ref is None or not self.grid_model.is_editable(ref[0]) or self.grid_model.kind_at(ref[1]) != "lesson":
            return
        old = self.grid_model.cell(*ref)
        text = self.ask_comment(old.comment or "")
        if text is not None:
            self._save(*ref, old.attendance, old.grade, text)

    def ask_comment(self, current: str) -> str | None:
        """Показує діалог; повертає новий текст або None, якщо скасовано."""
        dialog = CommentDialog(current, self)
        if dialog.exec():
            return dialog.text()
        return None

    # ------------------------------------------------------------------
    # Події
    # ------------------------------------------------------------------

    def currentChanged(self, current: QModelIndex, previous: QModelIndex) -> None:
        self.flush_pending()
        super().currentChanged(current, previous)

    def focusOutEvent(self, event) -> None:
        self.flush_pending()
        super().focusOutEvent(event)

    def _move(self, d_row: int, d_col: int) -> None:
        ref = self._ref()
        if ref is None:
            return
        row = min(max(ref[0] + d_row, 0), self.grid_model.rowCount() - 1)
        column = min(max(ref[1] + d_col, 0), self.grid_model.columnCount() - 1)
        self.select_cell(row, column)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        ref = self._ref()
        key, mods = event.key(), event.modifiers()
        text = event.text().lower()
        chain = bool(
            ref and self.grid_model.pending == ref and len(text) == 1 and text in "012"
            and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        )
        if not chain:
            self.flush_pending()
        if ref is None:
            super().keyPressEvent(event)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._move(1, 0)
        elif key == Qt.Key.Key_Tab and not mods & Qt.KeyboardModifier.ShiftModifier:
            self._move(0, 1)
        elif key in (Qt.Key.Key_Backtab, Qt.Key.Key_Tab):
            self._move(0, -1)
        elif mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            super().keyPressEvent(event)
        elif key == Qt.Key.Key_F2:
            self.edit_comment()  # для не-урочних стовпців нічого не робить
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.grid_model.is_editable(ref[0]):
                if self.grid_model.kind_at(ref[1]) != "lesson":
                    self._save_override(*ref, None)
                else:
                    old = self.grid_model.cell(*ref)
                    self._save(*ref, "present", None, old.comment)
        elif len(text) == 1 and text in "0123456789":
            if self.grid_model.is_editable(ref[0]):
                self._grade_key(int(text), *ref)
        elif text in ABSENT_KEYS + SICK_KEYS + LATE_KEYS and text:
            if self.grid_model.is_editable(ref[0]):
                kind = self.grid_model.kind_at(ref[1])
                if kind == "lesson":
                    mark = "absent" if text in ABSENT_KEYS else "sick" if text in SICK_KEYS else "late"
                    self._mark_key(mark, *ref)
                elif kind != "notebook" and text in ABSENT_KEYS:
                    self._save_override(*ref, None, na=True)  # «н» у обчислюваній клітинці → н/а
        elif key in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
            Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        ):
            super().keyPressEvent(event)
        # решту клавіш ігноруємо (щоб не спрацьовував пошук за першою літерою)

    # --- заголовки стовпців ---

    def _column_at(self, section: int) -> GridColumn | None:
        return self.grid_model.columns[section] if 0 <= section < len(self.grid_model.columns) else None

    def _on_header_double_click(self, section: int) -> None:
        column = self._column_at(section)
        if column is not None and column.kind == "lesson" and not self.grid_model.read_only:
            self.lesson_edit_requested.emit(column.id)

    def _on_header_menu(self, pos: QPoint) -> None:
        column = self._column_at(self.horizontalHeader().logicalIndexAt(pos))
        if column is None or column.kind not in ("lesson", "thematic", "notebook") or self.grid_model.read_only:
            return
        menu = QMenu(self)
        if column.kind == "lesson":
            first = menu.addAction("Редагувати урок")
            second = menu.addAction("Видалити урок")
        else:
            first = menu.addAction("Перемістити…")
            second = menu.addAction("Видалити")
        chosen = menu.exec(self.horizontalHeader().mapToGlobal(pos))
        if chosen is None:
            return
        if column.kind == "lesson":
            (self.lesson_edit_requested if chosen is first else self.lesson_delete_requested).emit(column.id)
        else:
            (self.column_move_requested if chosen is first else self.column_delete_requested).emit(column.id)

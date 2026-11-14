"""Експорт журналу в Excel: вибір стовпців за періодом і готова таблиця `ExportTable` (без Qt і без openpyxl).

Усі оцінки беруться з JournalApi.get_grid (тематичні, семестрові, річні — вже пораховані сервісом),
тут нічого не рахується заново. Тексти клітинок — спільні з екраном (services/grid_text.py).
Специфікація: docs/specs/excel-export.md.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date

from journal.services.grid_text import (
    EXTRA_COLUMN_TYPES,
    FINAL_COLUMN_TITLES,
    LESSON_TYPES,
    cell_text,
    computed_text,
)
from journal.services.journal_types import (
    CellInfo,
    GridColumn,
    GridData,
    JournalApi,
    JournalError,
    JournalInfo,
    semester_for_date,
)

EMPTY_PERIOD_TEXT = "У цьому періоді немає ні уроків, ні підсумкових стовпців. Оберіть інший період."
BAD_RANGE_TEXT = "Дата «з» має бути не пізнішою за дату «по»"

PRESET_CURRENT = "Поточний семестр"
PRESET_FIRST = "I семестр"
PRESET_SECOND = "II семестр"
PRESET_YEAR = "Весь рік"
PRESET_MONTH = "Цей місяць"
PRESET_NAMES = (PRESET_CURRENT, PRESET_FIRST, PRESET_SECOND, PRESET_YEAR, PRESET_MONTH)

_EMPTY = CellInfo("present", None, None)
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]+')


class ExportError(Exception):
    """Помилка експорту з повідомленням, яке можна показати користувачу."""


@dataclass(frozen=True)
class ExportColumn:
    kind: str                  # lesson | thematic | notebook | semester | annual
    header: str                # рядок 3: номер/скорочення («1», «Т», «Тем 1», «Сем I», «Річна»)
    date_text: str = ""        # рядок 4: «dd.mm» (порожньо для стовпців без дати)
    lesson_type: str | None = None


@dataclass(frozen=True)
class ExportCell:
    text: str = ""
    number: int | None = None  # заповнено, якщо клітинка — просто оцінка (Excel зможе рахувати)
    comment: str | None = None


@dataclass(frozen=True)
class ExportRow:
    number: int | None         # номер у класі (None — вибулий)
    name: str
    cells: list[ExportCell]
    archived: bool = False


@dataclass(frozen=True)
class ExportLesson:
    number: int
    lesson_date: date
    type_name: str
    topic: str
    homework: str


@dataclass(frozen=True)
class ExportTable:
    title: str
    generated: str
    date_from: date
    date_to: date
    columns: list[ExportColumn]
    rows: list[ExportRow]
    lessons: list[ExportLesson] = field(default_factory=list)


# ---------- період ----------


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def semester_range(info: JournalInfo, semester: int) -> tuple[date, date]:
    """Перший і останній день семестру (межі — з місяців, налаштованих у журналі)."""
    b, year = info.boundaries, info.school_year
    start_m, end_m = (b.s1_start, b.s1_end) if semester == 1 else (b.s2_start, b.s2_end)
    return date(b.calendar_year(year, start_m), start_m, 1), month_end(b.calendar_year(year, end_m), end_m)


def period_presets(info: JournalInfo, today: date) -> dict[str, tuple[date, date]]:
    """Готові періоди для діалогу. Під час канікул «Поточний семестр» = найближчий минулий (чи перший)."""
    first, second = semester_range(info, 1), semester_range(info, 2)
    try:
        current = semester_for_date(today, info.boundaries)
    except JournalError:  # канікули
        current = 2 if today > first[1] else 1
    return {
        PRESET_CURRENT: first if current == 1 else second,
        PRESET_FIRST: first,
        PRESET_SECOND: second,
        PRESET_YEAR: (first[0], second[1]),
        PRESET_MONTH: (today.replace(day=1), month_end(today.year, today.month)),
    }


def _semester_last_day(info: JournalInfo, semester: int) -> date:
    return semester_range(info, semester)[1]


# ---------- імена файлів ----------


def safe_file_part(text: str) -> str:
    """Частина імені файлу без символів, заборонених у Windows, і без пробілів."""
    cleaned = _UNSAFE_NAME.sub("_", text).strip("._ ")
    return cleaned or "журнал"


def suggest_file_name(info: JournalInfo, date_from: date, date_to: date) -> str:
    """«9-А_Математика_2026-09-01_2026-12-31.xlsx»."""
    return (
        f"{safe_file_part(info.class_name)}_{safe_file_part(info.subject_name)}_"
        f"{date_from:%Y-%m-%d}_{date_to:%Y-%m-%d}.xlsx"
    )


# ---------- побудова таблиці ----------


def _lesson_header(lesson, abbr: str) -> str:
    """Звичайний урок — наскрізний номер; КР/ЛР/СР/Т/Пр — скорочення, як на екрані."""
    return abbr or str(lesson.number)


def _to_cell(text: str, comment: str | None = None) -> ExportCell:
    number = int(text) if text.isascii() and text.isdigit() else None
    return ExportCell(text, number, comment)


def build_export_table(
    api: JournalApi,
    teacher_id: int,
    journal_id: int,
    date_from: date,
    date_to: date,
    *,
    today: date | None = None,
) -> ExportTable:
    """Таблиця для експорту за період [date_from, date_to] (включно). Порожній період → ExportError."""
    if date_from > date_to:
        raise ExportError(BAD_RANGE_TEXT)
    today = today or date.today()
    grids = {semester: api.get_grid(teacher_id, journal_id, semester) for semester in (1, 2)}
    info = grids[1].journal

    def in_range(day: date) -> bool:
        return date_from <= day <= date_to

    # Вибір стовпців у порядку екрана: спершу I семестр, потім II.
    chosen: list[tuple[GridData, GridColumn]] = []
    for semester in (1, 2):
        grid = grids[semester]
        lessons = {x.id: x for x in grid.lessons}
        extras = {x.id: x for x in grid.extra_columns}
        for column in grid.columns:
            if column.kind == "lesson":
                keep = in_range(lessons[column.id].lesson_date)
            elif column.kind in ("thematic", "notebook"):
                keep = in_range(extras[column.id].after_date)
            elif column.kind == "semester":
                keep = in_range(_semester_last_day(info, semester))
            else:  # annual — після останнього дня II семестру
                keep = in_range(_semester_last_day(info, 2))
            if keep:
                chosen.append((grid, column))
    if not chosen:
        raise ExportError(EMPTY_PERIOD_TEXT)

    columns: list[ExportColumn] = []
    for grid, column in chosen:
        if column.kind == "lesson":
            lesson = next(x for x in grid.lessons if x.id == column.id)
            abbr = LESSON_TYPES[lesson.lesson_type][1]
            columns.append(
                ExportColumn("lesson", _lesson_header(lesson, abbr), f"{lesson.lesson_date:%d.%m}", lesson.lesson_type)
            )
        elif column.kind in ("thematic", "notebook"):
            extra = next(x for x in grid.extra_columns if x.id == column.id)
            columns.append(ExportColumn(column.kind, f"{EXTRA_COLUMN_TYPES[column.kind][1]} {extra.ordinal}"))
        elif column.kind == "semester":
            columns.append(ExportColumn("semester", "Сем I" if grid.semester == 1 else "Сем II"))
        else:
            columns.append(ExportColumn("annual", FINAL_COLUMN_TITLES["annual"][1]))

    # Учні: однаковий список для обох семестрів; вибулий — лише якщо в періоді в нього є запис.
    students = list(grids[1].students)
    known = {s.id for s in students}
    students += [s for s in grids[2].students if s.id not in known]
    selected_lessons = {
        (grid.semester, column.id) for grid, column in chosen if column.kind == "lesson"
    }

    rows: list[ExportRow] = []
    for student in students:
        has_entry = any(
            (student.id, lesson_id) in grid.cells
            for grid in grids.values()
            for sem, lesson_id in selected_lessons
            if sem == grid.semester
        )
        if student.archived and not has_entry:
            continue
        cells: list[ExportCell] = []
        for grid, column in chosen:
            if column.kind == "lesson":
                cell = grid.cells.get((student.id, column.id), _EMPTY)
                cells.append(_to_cell(cell_text(cell), cell.comment))
                continue
            key = (
                ("semester", grid.semester) if column.kind == "semester"
                else ("annual", 0) if column.kind == "annual"
                else (column.kind, column.id)
            )
            cells.append(_to_cell(computed_text(column.kind, grid.computed.get((student.id, key)))))
        if student.archived:
            rows.append(ExportRow(None, f"{student.full_name} (вибув)", cells, archived=True))
        else:
            rows.append(ExportRow(student.position, student.full_name, cells))

    lessons = [
        ExportLesson(
            x.number, x.lesson_date, LESSON_TYPES[x.lesson_type][0], x.topic or "", x.homework or ""
        )
        for grid in grids.values()
        for x in grid.lessons
        if in_range(x.lesson_date)
    ]
    lessons.sort(key=lambda x: (x.lesson_date, x.number))

    return ExportTable(
        title=f"{info.subject_name}, {info.class_name} — {date_from:%d.%m.%Y}–{date_to:%d.%m.%Y}",
        generated=f"Сформовано {today:%d.%m.%Y}",
        date_from=date_from,
        date_to=date_to,
        columns=columns,
        rows=rows,
        lessons=lessons,
    )

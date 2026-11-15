"""Запис ExportTable у .xlsx (openpyxl, без Qt). Фіксована друкарська палітра — це документ, а не інтерфейс.

Запис атомарний: спершу тимчасовий файл у тій самій папці, потім заміна; при помилці нічого не лишається.
"""
import contextlib
import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from journal.services.export_service import ExportError, ExportTable

LOCKED_TEXT = "Не вдалося зберегти файл: він, мабуть, відкритий в Excel. Закрийте його й спробуйте ще раз."
FAILED_TEXT = "Не вдалося записати файл у цю папку. Перевірте доступ до папки та вільне місце й спробуйте ще раз."

SHEET_GRADES = "Журнал"
SHEET_LESSONS = "Уроки"
HEADER_ROWS = 4
FIRST_GRADE_COLUMN = 3
GRADE_COLUMN_WIDTH = 6.5
COMMENT_AUTHOR = "Журнал"

_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)
_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
_HEADER_FILL = PatternFill("solid", fgColor="F2F2F2")
_SOFT_FILL = PatternFill("solid", fgColor="DDEBF7")
_SOFT_KINDS = {"thematic", "semester", "annual"}


class ExportWriteError(ExportError):
    """Файл не вдалося записати (повідомлення — для користувача)."""


def _put(cell, value) -> None:
    """Текст пишемо як текст: значення, що починається з «=», не стає формулою."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
    cell.value = value
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"


def build_workbook(table: ExportTable) -> Workbook:
    wb = Workbook()
    wb.properties.creator = "Електронний журнал"
    ws = wb.active
    ws.title = SHEET_GRADES

    title, generated = ws.cell(1, 1), ws.cell(2, 1)
    _put(title, table.title)
    _put(generated, table.generated)
    title.font = Font(bold=True, size=14)
    generated.font = Font(italic=True, color="666666")

    for column, text in ((1, "№"), (2, "Учень")):
        ws.merge_cells(start_row=3, start_column=column, end_row=4, end_column=column)
        head = ws.cell(3, column)
        _put(head, text)
        head.font = Font(bold=True)
        head.alignment = _CENTER
        for row in (3, 4):
            ws.cell(row, column).border = _BORDER
            ws.cell(row, column).fill = _HEADER_FILL

    for offset, column in enumerate(table.columns):
        index = FIRST_GRADE_COLUMN + offset
        fill = _SOFT_FILL if column.kind in _SOFT_KINDS else _HEADER_FILL
        top, bottom = ws.cell(3, index), ws.cell(4, index)
        _put(top, column.header)
        _put(bottom, column.date_text or None)
        top.font = Font(bold=True)
        bottom.font = Font(size=9, color="555555")
        for head in (top, bottom):
            head.alignment = _CENTER
            head.border = _BORDER
            head.fill = fill
        ws.column_dimensions[get_column_letter(index)].width = GRADE_COLUMN_WIDTH

    for number, row in enumerate(table.rows, start=HEADER_ROWS + 1):
        num_cell = ws.cell(number, 1, row.number)
        name_cell = ws.cell(number, 2)
        _put(name_cell, row.name)
        num_cell.alignment, name_cell.alignment = _CENTER, _LEFT
        for cell in (num_cell, name_cell):
            cell.border = _BORDER
            if row.archived:
                cell.font = Font(italic=True, color="777777")
        for offset, item in enumerate(row.cells):
            cell = ws.cell(number, FIRST_GRADE_COLUMN + offset)
            if item.number is not None:
                cell.value = item.number
            elif item.text:
                _put(cell, item.text)
            cell.alignment = _CENTER
            cell.border = _BORDER
            if item.comment:
                comment = Comment(ILLEGAL_CHARACTERS_RE.sub("", item.comment), COMMENT_AUTHOR)
                comment.width, comment.height = 220, 90
                cell.comment = comment

    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 32
    ws.freeze_panes = ws.cell(HEADER_ROWS + 1, FIRST_GRADE_COLUMN).coordinate  # C5
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"3:{HEADER_ROWS}"

    _lessons_sheet(wb.create_sheet(SHEET_LESSONS), table)
    return wb


def _lessons_sheet(ws, table: ExportTable) -> None:
    for column, text in enumerate(("№", "Дата", "Тип", "Тема", "Домашнє завдання"), start=1):
        head = ws.cell(1, column, text)
        head.font = Font(bold=True)
        head.alignment = _CENTER
        head.border = _BORDER
        head.fill = _HEADER_FILL
    for number, lesson in enumerate(table.lessons, start=2):
        values = (lesson.number, f"{lesson.lesson_date:%d.%m.%Y}", lesson.type_name, lesson.topic, lesson.homework)
        for column, value in enumerate(values, start=1):
            cell = ws.cell(number, column)
            _put(cell, value or None)
            cell.border = _BORDER
            cell.alignment = _CENTER if column <= 2 else _WRAP
    for column, width in zip("ABCDE", (6, 12, 22, 45, 45), strict=True):
        ws.column_dimensions[column].width = width
    ws.freeze_panes = "A2"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = "1:1"


def write_export(table: ExportTable, path: str | Path) -> Path:
    """Записує файл атомарно. Помилки диска → ExportWriteError з українським повідомленням."""
    target = Path(path)
    temp_name: str | None = None
    try:
        workbook = build_workbook(table)
        try:
            handle, temp_name = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=target.parent)
            os.close(handle)
            workbook.save(temp_name)
        except OSError:
            raise ExportWriteError(FAILED_TEXT) from None
        try:
            os.replace(temp_name, target)
            temp_name = None
        except OSError:  # найчастіше — файл відкритий в Excel (PermissionError)
            raise ExportWriteError(LOCKED_TEXT) from None
    finally:
        if temp_name is not None:
            with contextlib.suppress(OSError):
                os.remove(temp_name)
    return target

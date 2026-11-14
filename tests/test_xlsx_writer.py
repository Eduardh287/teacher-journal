"""Запис експорту в .xlsx: файл відкривається openpyxl, перевіряємо вміст і атомарність."""
import os
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from journal.models import Subject, Teacher
from journal.services import xlsx_writer
from journal.services.class_service import ClassService
from journal.services.export_service import (
    ExportCell,
    ExportColumn,
    ExportLesson,
    ExportRow,
    ExportTable,
    build_export_table,
)
from journal.services.journal_service import JournalService
from journal.services.xlsx_writer import ExportWriteError, write_export


def sample_table() -> ExportTable:
    return ExportTable(
        title="Математика, 9-А — 01.09.2025–31.12.2025",
        generated="Сформовано 20.05.2026",
        date_from=date(2025, 9, 1),
        date_to=date(2025, 12, 31),
        columns=[
            ExportColumn("lesson", "1", "02.09", "regular"),
            ExportColumn("lesson", "КР", "09.09", "test"),
            ExportColumn("thematic", "Тем 1"),
            ExportColumn("semester", "Сем I"),
        ],
        rows=[
            ExportRow(1, "Андрієнко Іван", [ExportCell("8", 8), ExportCell("з 9", None, "запізнився"),
                                              ExportCell("н/а"), ExportCell("")]),
            ExportRow(None, "=SUM(A1) Вибулий (вибув)", [ExportCell("н"), ExportCell(""), ExportCell(""),
                                                          ExportCell("")], archived=True),
        ],
        lessons=[ExportLesson(1, date(2025, 9, 2), "Звичайний урок", "Дроби", "п. 3")],
    )


def test_workbook_content(tmp_path):
    path = write_export(sample_table(), tmp_path / "out.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames == ["Журнал", "Уроки"]
    ws = wb["Журнал"]
    assert ws["A1"].value == "Математика, 9-А — 01.09.2025–31.12.2025" and ws["A1"].font.bold
    assert ws["A2"].value == "Сформовано 20.05.2026"
    assert [ws.cell(3, c).value for c in range(1, 7)] == ["№", "Учень", "1", "КР", "Тем 1", "Сем I"]
    assert [ws.cell(4, c).value for c in range(3, 7)] == ["02.09", "09.09", None, None]
    # числа — числа, позначки — текст
    assert ws["C5"].value == 8 and isinstance(ws["C5"].value, int)
    assert ws["D5"].value == "з 9" and ws["E5"].value == "н/а"
    assert ws["A5"].value == 1 and ws["A6"].value is None
    assert ws["C6"].value == "н"
    # «=…» не стає формулою
    assert ws["B6"].data_type == "s" and ws["B6"].value.startswith("=SUM")
    assert ws["C5"].alignment.horizontal == "center"
    # коментар
    assert ws["D5"].comment is not None and ws["D5"].comment.text == "запізнився"
    assert ws["C5"].comment is None


def test_layout_and_print_setup(tmp_path):
    ws = load_workbook(write_export(sample_table(), tmp_path / "out.xlsx"))["Журнал"]
    assert ws.freeze_panes == "C5"
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_title_rows == "$3:$4"
    assert ws.column_dimensions["C"].width == ws.column_dimensions["D"].width == xlsx_writer.GRADE_COLUMN_WIDTH
    assert ws["E3"].fill.fgColor.rgb.endswith("DDEBF7") and ws["C3"].fill.fgColor.rgb.endswith("F2F2F2")


def test_lessons_sheet(tmp_path):
    ws = load_workbook(write_export(sample_table(), tmp_path / "out.xlsx"))["Уроки"]
    assert [c.value for c in ws[1]] == ["№", "Дата", "Тип", "Тема", "Домашнє завдання"]
    assert [c.value for c in ws[2]] == [1, "02.09.2025", "Звичайний урок", "Дроби", "п. 3"]


def test_overwrite_existing_file(tmp_path):
    target = tmp_path / "out.xlsx"
    target.write_bytes(b"old")
    write_export(sample_table(), target)
    assert load_workbook(target).sheetnames == ["Журнал", "Уроки"]
    assert [p.name for p in tmp_path.iterdir()] == ["out.xlsx"]  # тимчасових файлів не лишилось


def test_missing_folder_leaves_nothing(tmp_path):
    with pytest.raises(ExportWriteError) as error:
        write_export(sample_table(), tmp_path / "немає" / "out.xlsx")
    assert str(error.value) == xlsx_writer.FAILED_TEXT
    assert list(tmp_path.iterdir()) == []


def test_locked_file_keeps_old_content_and_no_partial(tmp_path, monkeypatch):
    target = tmp_path / "out.xlsx"
    target.write_bytes(b"old")

    def locked(src, dst):
        raise PermissionError("file is open")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(ExportWriteError) as error:
        write_export(sample_table(), target)
    assert str(error.value) == xlsx_writer.LOCKED_TEXT
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.xlsx"]


def test_save_failure_cleans_temp(tmp_path, monkeypatch):
    from openpyxl import Workbook

    def broken(self, name):
        Path(name).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(Workbook, "save", broken)
    with pytest.raises(ExportWriteError):
        write_export(sample_table(), tmp_path / "out.xlsx")
    assert list(tmp_path.iterdir()) == []


# ---------- справжній сервіс і БД (журнал_test, відкат) ----------


def test_export_from_real_service(session, tmp_path):
    teacher = Teacher(username="pytest_export", password_hash="x", full_name="Т")
    session.add(teacher)
    session.flush()
    classes, svc = ClassService(session), JournalService(session)
    c = classes.create_class(teacher.id, "9-А", "2026-2027")
    classes.add_student(teacher.id, c.id, "Демо Андрій")
    classes.add_student(teacher.id, c.id, "Демо Богдана")
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = svc.create_journal(teacher.id, c.id, subject.id)
    students = [s.id for s in classes.list_students(teacher.id, c.id)]
    lessons = [
        svc.create_lesson(teacher.id, journal.id, d, kind, topic)
        for d, kind, topic in (
            (date(2026, 9, 1), "regular", "Повторення"),
            (date(2026, 9, 8), "regular", "Дроби"),
            (date(2026, 9, 15), "test", "Контрольна"),
            (date(2027, 1, 12), "regular", "Рівняння"),
        )
    ]
    svc.set_cell(teacher.id, lessons[0].id, students[0], "present", 9, None)
    svc.set_cell(teacher.id, lessons[1].id, students[0], "late", 8, "спізнився")
    svc.set_cell(teacher.id, lessons[1].id, students[1], "absent", None, None)
    svc.set_cell(teacher.id, lessons[2].id, students[0], "present", 11, None)
    svc.set_cell(teacher.id, lessons[2].id, students[1], "present", 7, None)
    svc.set_cell(teacher.id, lessons[3].id, students[0], "present", 10, None)
    svc.create_column(teacher.id, journal.id, "thematic", lessons[2].id)
    svc.create_column(teacher.id, journal.id, "notebook", lessons[2].id)

    table = build_export_table(svc, teacher.id, journal.id, date(2026, 9, 1), date(2027, 6, 30), today=date(2026, 11, 15))
    path = write_export(table, tmp_path / "real.xlsx")
    ws = load_workbook(path)["Журнал"]
    kinds = [c.kind for c in table.columns]
    assert kinds == ["lesson", "lesson", "lesson", "thematic", "notebook", "semester", "lesson", "semester", "annual"]
    assert ws["B5"].value == "Демо Андрій" and ws["B6"].value == "Демо Богдана"
    assert [ws.cell(5, col).value for col in range(3, 6)] == [9, "з 8", 11]
    # тематична й семестрова — як порахував сервіс (середнє 9, 8, 11 → 9; 7,5 → 8)
    assert ws.cell(5, 6).value == 9 and ws.cell(5, 8).value == 9
    assert ws.cell(6, 5).value == 7 and ws.cell(6, 4).value == "н"

"""Експорт в Excel: вибір стовпців за періодом, тексти клітинок, вибулі учні, імена файлів."""
from dataclasses import replace
from datetime import date

import pytest

from journal.services import grid_text
from journal.services.export_service import (
    EMPTY_PERIOD_TEXT,
    ExportError,
    build_export_table,
    period_presets,
    safe_file_part,
    suggest_file_name,
)
from journal.services.journal_types import CellInfo, ComputedCell
from tests.fakes.fake_journal_service import FakeJournalService

S1 = [date(2025, 9, 2), date(2025, 9, 9), date(2025, 10, 7)]
S2 = [date(2026, 1, 13), date(2026, 3, 3)]
TODAY = date(2026, 5, 20)


@pytest.fixture
def fake() -> FakeJournalService:
    service = FakeJournalService(["Андрієнко Іван", "Бондаренко Олена"], archived_students=("Вибулий Петро",))
    ids = [service.add_lesson(d, kind) for d, kind in zip(S1 + S2, ("regular", "test", "regular", "quiz", "regular"))]
    service.ids = ids
    for sid in (1, 2):
        service.put_cell(sid, ids[0], grade=7 + sid)
    service.put_cell(1, ids[1], attendance="absent")
    service.put_cell(2, ids[1], attendance="late", grade=9, comment="прийшов із запізненням")
    service.put_cell(1, ids[2], attendance="sick")
    service.put_cell(1, ids[3], grade=10)
    service.add_column("thematic", ids[1])   # sem I, після 2-го уроку (09.09)
    service.add_column("notebook", ids[3])   # sem II, після 13.01
    return service


def build(fake, start, end):
    return build_export_table(fake, 1, 1, start, end, today=TODAY)


def headers(table):
    return [(c.kind, c.header, c.date_text) for c in table.columns]


def test_lessons_in_and_out_of_range(fake):
    table = build(fake, date(2025, 9, 9), date(2025, 10, 7))
    assert [(c.kind, c.date_text) for c in table.columns if c.kind == "lesson"] == [
        ("lesson", "09.09"), ("lesson", "07.10"),
    ]
    assert [x.lesson_date for x in table.lessons] == [S1[1], S1[2]]


def test_thematic_included_only_when_anchor_in_range(fake):
    inside = build(fake, date(2025, 9, 9), date(2025, 9, 9))
    outside = build(fake, date(2025, 10, 1), date(2025, 10, 31))
    assert [c.kind for c in inside.columns] == ["lesson", "thematic"]
    assert "thematic" not in [c.kind for c in outside.columns]


def test_notebook_anchor_rule(fake):
    table = build(fake, date(2026, 1, 13), date(2026, 1, 13))
    assert [(c.kind, c.header) for c in table.columns] == [("lesson", "Т"), ("notebook", "Зош 1")]


def test_semester_and_annual_inclusion_rules(fake):
    # Останній день I семестру — 31.12.2025; II — 30.06.2026.
    only_sem1_end = build(fake, date(2025, 12, 31), date(2025, 12, 31))
    assert [c.kind for c in only_sem1_end.columns] == ["semester"]
    assert only_sem1_end.columns[0].header == "Сем I"
    before_end = build(fake, date(2026, 1, 1), date(2026, 6, 29))
    assert "semester" not in [c.kind for c in before_end.columns]
    assert "annual" not in [c.kind for c in before_end.columns]
    last_day = build(fake, date(2026, 6, 30), date(2026, 6, 30))
    assert [(c.kind, c.header) for c in last_day.columns] == [("semester", "Сем II"), ("annual", "Річна")]


def test_cross_semester_keeps_app_order(fake):
    table = build(fake, date(2025, 9, 1), date(2026, 6, 30))
    assert [c.kind for c in table.columns] == [
        "lesson", "lesson", "thematic", "lesson", "semester",
        "lesson", "notebook", "lesson", "semester", "annual",
    ]
    assert [c.header for c in table.columns if c.kind == "semester"] == ["Сем I", "Сем II"]


def test_empty_range_is_friendly_error(fake):
    with pytest.raises(ExportError) as error:
        build(fake, date(2025, 11, 1), date(2025, 11, 30))
    assert str(error.value) == EMPTY_PERIOD_TEXT
    with pytest.raises(ExportError):
        build(fake, date(2025, 10, 1), date(2025, 9, 1))


def test_cell_texts_match_app(fake):
    table = build(fake, date(2025, 9, 1), date(2025, 12, 31))
    first, second = table.rows[0], table.rows[1]
    texts = [c.text for c in first.cells]
    assert texts[:2] == ["8", "н"]
    assert second.cells[1].text == "з 9" and second.cells[1].number is None
    assert second.cells[1].comment == "прийшов із запізненням"
    assert first.cells[2].text == "8"  # тематична: середнє єдиної оцінки періоду
    assert first.cells[3].text == "хв"
    assert first.cells[0].number == 8
    # клітинки уроків — рівно та сама функція, що малює екран
    assert grid_text.cell_text(fake.get_grid(1, 1, 1).cells[(1, fake.ids[1])]) == "н"
    assert grid_text.cell_text(CellInfo("late", 9, None)) == "з 9"


def test_computed_columns_use_service_values_and_na(fake):
    fake.put_final(2, "semester", 1, 11)          # ручна семестрова
    fake.put_extra_grade(1, 2, None, na=True)     # ручне н/а в тематичній
    table = build(fake, date(2025, 9, 1), date(2025, 12, 31))
    kinds = [c.kind for c in table.columns]
    sem_idx, them_idx = kinds.index("semester"), kinds.index("thematic")
    assert table.rows[1].cells[sem_idx].text == "11" and table.rows[1].cells[sem_idx].number == 11
    assert table.rows[1].cells[them_idx].text == "н/а" and table.rows[1].cells[them_idx].number is None


def test_withdrawn_student_only_with_entries_in_range(fake):
    ids = fake.ids
    assert [r.name for r in build(fake, date(2025, 9, 1), date(2025, 12, 31)).rows] == [
        "Андрієнко Іван", "Бондаренко Олена",
    ]
    fake.put_cell(3, ids[2], grade=5)  # вибулий: запис 07.10
    table = build(fake, date(2025, 10, 1), date(2025, 10, 31))
    assert [r.name for r in table.rows] == ["Андрієнко Іван", "Бондаренко Олена", "Вибулий Петро (вибув)"]
    assert table.rows[2].archived and table.rows[2].number is None
    other = build(fake, date(2025, 9, 1), date(2025, 9, 30))  # запис поза періодом
    assert all(not r.archived for r in other.rows)


def test_title_and_lessons_sheet_data(fake):
    fake.lessons[1]["topic"] = "Рівняння"
    table = build(fake, date(2025, 9, 1), date(2025, 12, 31))
    assert table.title == "Математика, 9-А — 01.09.2025–31.12.2025"
    assert table.generated == "Сформовано 20.05.2026"
    assert [(x.number, x.type_name, x.topic) for x in table.lessons][:2] == [
        (1, "Звичайний урок", ""), (2, "Контрольна робота", "Рівняння"),
    ]


def test_headers_use_numbers_and_abbreviations(fake):
    table = build(fake, date(2025, 9, 1), date(2025, 9, 30))
    assert headers(table)[:3] == [("lesson", "1", "02.09"), ("lesson", "КР", "09.09"), ("thematic", "Тем 1", "")]


def test_period_presets(fake):
    presets = period_presets(fake.journal, TODAY)
    assert presets["Поточний семестр"] == (date(2026, 1, 1), date(2026, 6, 30))
    assert presets["I семестр"] == (date(2025, 9, 1), date(2025, 12, 31))
    assert presets["Весь рік"] == (date(2025, 9, 1), date(2026, 6, 30))
    assert presets["Цей місяць"] == (date(2026, 5, 1), date(2026, 5, 31))
    vacation = period_presets(fake.journal, date(2026, 7, 10))
    assert vacation["Поточний семестр"] == (date(2026, 1, 1), date(2026, 6, 30))
    early = period_presets(replace(fake.journal), date(2025, 8, 20))
    assert early["Поточний семестр"][0] == date(2025, 9, 1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("9-А", "9-А"),
        ('Алгебра: "частина 1"/2', "Алгебра_частина_1_2"),
        ("  a*b?c<d>e|f\\g ", "a_b_c_d_e_f_g"),
        ("...", "журнал"),
        ("Фізика  і\tматематика", "Фізика_і_математика"),
    ],
)
def test_safe_file_part(text, expected):
    assert safe_file_part(text) == expected


def test_suggest_file_name(fake):
    info = replace(fake.journal, class_name="9/А", subject_name="Фізика: 1")
    assert suggest_file_name(info, date(2025, 9, 1), date(2025, 12, 31)) == "9_А_Фізика_1_2025-09-01_2025-12-31.xlsx"


def test_computed_cell_text_helpers():
    assert grid_text.computed_text("thematic", ComputedCell(None, True, 0, 0, None, False)) == "н/а"
    assert grid_text.computed_text("notebook", ComputedCell(None, False, 0, 0, 9, False)) == "9"
    assert grid_text.computed_text("thematic", None) == ""

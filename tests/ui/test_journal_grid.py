"""Тести таблиці журналу: клавіатурне введення, автозбереження, лише-читання, уроки."""
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from journal.services.class_service import default_school_year
from journal.services.journal_types import (
    CellInfo,
    JournalCandidate,
    JournalError,
    LessonInfo,
    semester_for_date,
)
from journal.ui import journal_dialogs, journals_page
from journal.ui.journal_grid import header_text
from tests.fakes.fake_journal_service import FakeJournalService
from tests.ui.conftest import type_text

L1, L2 = 1, 2  # id уроків із фікстури fake
S1, S2, S_ARCH = 1, 2, 3  # id учнів


def sets(fake):
    return fake.calls_of("set_cell")


def cell_of(page, row, col):
    return page.grid_view.grid_model.cell(row, col)


def skip_if_vacation():
    today = date.today()
    try:
        semester_for_date(today)
    except JournalError:
        pytest.skip("канікули: уроки не створюються")
    return today


# --- заголовки ---

def test_header_text_for_each_lesson_type():
    d = date(2025, 9, 2)
    assert header_text(LessonInfo(1, d, 1, "regular", None, 0)) == "02.09"
    assert header_text(LessonInfo(1, d, 1, "test", None, 0)) == "02.09\nКР"
    assert header_text(LessonInfo(1, d, 1, "lab", None, 0)) == "02.09\nЛР"
    assert header_text(LessonInfo(1, d, 1, "independent", None, 0)) == "02.09\nСР"
    assert header_text(LessonInfo(1, d, 1, "quiz", None, 0)) == "02.09\nТ"
    assert header_text(LessonInfo(1, d, 1, "project", None, 0)) == "02.09\nПр"


def test_grid_layout(page):
    model = page.grid_view.grid_model
    assert model.rowCount() == 3 and model.columnCount() == 3  # 2 уроки + «Сем.»
    assert model.headerData(0, Qt.Orientation.Vertical) == "1. Коваленко Олена"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "09.09\nКР"
    tip = model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "Квадратні рівняння" in tip and "Контрольна робота" in tip
    assert page.grid_view.verticalHeader().width() == 240
    assert page.grid_view.columnWidth(0) == 56


# --- позначки ---

@pytest.mark.parametrize(
    ("text", "attendance"),
    [("н", "absent"), ("y", "absent"), ("х", "sick"), ("[", "sick"), ("з", "late"), ("p", "late"), ("Н", "absent")],
)
def test_mark_keys(page, fake, text, attendance):
    page.grid_view.select_cell(0, 0)
    type_text(page.grid_view, text)
    assert cell_of(page, 0, 0).attendance == attendance
    assert sets(fake)[-1][3] == attendance


@pytest.mark.parametrize("text", ["н", "х", "з"])
def test_same_mark_again_toggles_to_present(page, fake, text):
    page.grid_view.select_cell(0, 0)
    type_text(page.grid_view, text)
    type_text(page.grid_view, text)
    assert cell_of(page, 0, 0) == CellInfo("present", None, None)
    assert len(sets(fake)) == 2


def test_absent_clears_grade_late_keeps_it(page):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "7")
    type_text(view, "з")
    assert cell_of(page, 0, 0) == CellInfo("late", 7, None)
    type_text(view, "н")
    assert cell_of(page, 0, 0) == CellInfo("absent", None, None)


# --- оцінки ---

@pytest.mark.parametrize("digit", range(2, 10))
def test_digit_commits_immediately(page, fake, digit):
    page.grid_view.select_cell(0, 0)
    type_text(page.grid_view, str(digit))
    assert cell_of(page, 0, 0).grade == digit
    assert len(sets(fake)) == 1


def test_zero_alone_is_ignored(page, fake):
    page.grid_view.select_cell(0, 0)
    type_text(page.grid_view, "0")
    assert sets(fake) == []


@pytest.mark.parametrize(("second", "grade"), [("0", 10), ("1", 11), ("2", 12)])
def test_chain_makes_10_11_12_with_one_call(page, fake, second, grade):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    assert sets(fake) == []  # поки лише очікування
    assert view.grid_model.data(view.currentIndex()) == "1"
    type_text(view, second)
    assert len(sets(fake)) == 1
    assert cell_of(page, 0, 0).grade == grade
    assert view.grid_model.pending is None


def test_lone_one_commits_after_timeout(page, fake, qtbot):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    qtbot.waitUntil(lambda: cell_of(page, 0, 0).grade == 1, timeout=2000)
    assert len(sets(fake)) == 1


def test_pending_flushed_on_navigation(page, fake):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    view.select_cell(1, 0)
    assert cell_of(page, 0, 0).grade == 1
    assert len(sets(fake)) == 1


def test_pending_flushed_by_other_key(page, fake):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    type_text(view, "5")
    assert cell_of(page, 0, 0).grade == 5
    assert [c[4] for c in sets(fake)] == [1, 5]


def test_pending_flushed_on_semester_switch(page, fake):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    page.semester_buttons[2].click()
    assert fake.cells[(S1, L1)].grade == 1
    assert len(sets(fake)) == 1


def test_digit_on_absent_cell_sets_present(page):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "н")
    type_text(view, "9")
    assert cell_of(page, 0, 0) == CellInfo("present", 9, None)


# --- Del / коментар ---

@pytest.mark.parametrize("key", [Qt.Key.Key_Delete, Qt.Key.Key_Backspace])
def test_delete_keeps_comment(page, qtbot, monkeypatch, key):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "з")
    type_text(view, "6")
    monkeypatch.setattr(view, "ask_comment", lambda current: "Спізнився")
    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert cell_of(page, 0, 0) == CellInfo("late", 6, "Спізнився")
    qtbot.keyClick(view, key)
    assert cell_of(page, 0, 0) == CellInfo("present", None, "Спізнився")


def test_empty_comment_removes_it(page, fake, qtbot, monkeypatch):
    view = page.grid_view
    view.select_cell(0, 0)
    monkeypatch.setattr(view, "ask_comment", lambda current: "Є")
    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert cell_of(page, 0, 0).comment == "Є"
    monkeypatch.setattr(view, "ask_comment", lambda current: "")
    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert (S1, L1) not in fake.cells


def test_cancelled_comment_changes_nothing(page, fake, qtbot, monkeypatch):
    view = page.grid_view
    view.select_cell(0, 0)
    monkeypatch.setattr(view, "ask_comment", lambda current: None)
    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert sets(fake) == []


# --- навігація ---

def test_enter_moves_down_and_stops_at_edge(page, qtbot):
    view = page.grid_view
    view.select_cell(0, 0)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert view.currentIndex().row() == 1
    qtbot.keyClick(view, Qt.Key.Key_Enter)
    assert view.currentIndex().row() == 2
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert view.currentIndex().row() == 2


def test_tab_and_backtab_move_sideways_and_stop_at_edges(page, qtbot):
    view = page.grid_view
    view.select_cell(0, 0)
    qtbot.keyClick(view, Qt.Key.Key_Tab)
    assert view.currentIndex().column() == 1
    qtbot.keyClick(view, Qt.Key.Key_Tab)  # третій стовпець — «Сем.»
    qtbot.keyClick(view, Qt.Key.Key_Tab)
    assert view.currentIndex().column() == 2
    qtbot.keyClick(view, Qt.Key.Key_Backtab)
    assert view.currentIndex().column() == 1
    qtbot.keyClick(view, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert view.currentIndex().column() == 0
    qtbot.keyClick(view, Qt.Key.Key_Backtab)
    assert view.currentIndex().column() == 0


def test_cursor_stays_after_commit(page):
    page.grid_view.select_cell(0, 1)
    type_text(page.grid_view, "5")
    idx = page.grid_view.currentIndex()
    assert (idx.row(), idx.column()) == (0, 1)


# --- помилки збереження ---

def test_failed_save_keeps_old_value_and_shows_banner(page, fake):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "5")
    fake.fail_next = JournalError("Оцінка має бути від 1 до 12")
    type_text(view, "9")
    assert cell_of(page, 0, 0).grade == 5
    assert page.banner.isVisible()
    assert page.banner.text() == "Оцінка має бути від 1 до 12"


def test_unexpected_error_shows_generic_banner(page, fake):
    page.grid_view.select_cell(0, 0)
    fake.fail_next = RuntimeError("boom")
    type_text(page.grid_view, "5")
    assert cell_of(page, 0, 0).grade is None
    assert page.banner.text() == journals_page.GENERIC_ERROR_TEXT


def test_banner_hides_after_timer(page):
    page.show_banner("x")
    assert page.banner.isVisible()
    page._banner_timer.timeout.emit()
    assert not page.banner.isVisible()


# --- лише перегляд ---

def test_archived_student_row_is_read_only(page, fake):
    view = page.grid_view
    view.select_cell(2, 0)
    for text in ("5", "н", "з", "х"):
        type_text(view, text)
    assert sets(fake) == []
    assert cell_of(page, 2, 0) == CellInfo("present", None, None)


def test_archived_class_journal_is_editable(make_page):
    """Архівний журнал редагується (рішення автора); видалити його не можна."""
    service = FakeJournalService(["Коваленко Олена"], class_archived=True)
    service.add_lesson(date(2025, 9, 2))
    page = make_page(service)
    assert not page.grid_view.grid_model.read_only
    assert page.new_lesson_btn.isVisible()
    assert page.menu_btn.isVisible()
    assert not page.delete_journal_action.isEnabled()
    page.grid_view.select_cell(0, 0)
    type_text(page.grid_view, "5")
    assert len(service.calls_of("set_cell")) == 1
    page.new_lesson_today()
    assert len(service.calls_of("create_lesson")) == 1


# --- уроки ---

def test_ctrl_n_creates_lesson_for_today(make_page, qtbot):
    today = skip_if_vacation()
    service = FakeJournalService(["А Б", "В Г"], school_year=default_school_year(today))
    service.add_lesson(date(int(service.journal.school_year[:4]), 9, 1))
    page = make_page(service)
    assert page.new_lesson_shortcut.key().toString() == "Ctrl+N"
    page.new_lesson_shortcut.activated.emit()  # у offscreen-режимі вікно не активне, тож «натискання» емулюємо сигналом
    calls = service.calls_of("create_lesson")
    assert len(calls) == 1
    _, _, lesson_date, lesson_type, topic = calls[0]
    assert (lesson_date, lesson_type, topic) == (today, "regular", None)
    new_id = service.lessons[-1]["id"]
    # урок належить семестру за сьогоднішньою датою, сторінка перейшла на нього
    assert page._semester == semester_for_date(today)
    idx = page.grid_view.currentIndex()
    assert (idx.row(), idx.column()) == (0, page.grid_view.grid_model.column_of(new_id))


def test_ctrl_n_works_when_no_lessons_yet(make_page):
    today = skip_if_vacation()
    service = FakeJournalService(["А Б"], school_year=default_school_year(today))
    page = make_page(service)
    assert page.content_stack.currentIndex() == 1
    page.new_lesson_today()
    assert page.content_stack.currentIndex() == 0
    assert page.grid_view.grid_model.columnCount() == 2  # 1 урок + «Сем.»


def test_ctrl_n_error_shows_banner(page, fake):
    fake.fail_next = JournalError("Дата не належить навчальному року 2025-2026")
    page.new_lesson_today()
    assert page.banner.text().startswith("Дата не належить")


def test_delete_lesson_without_marks_uses_simple_confirm(page, fake, monkeypatch):
    monkeypatch.setattr(page, "_confirm", lambda text, accept: True)
    page._on_delete_lesson(L1)
    assert fake.calls_of("delete_lesson") == [("delete_lesson", L1)]
    assert page.grid_view.grid_model.columnCount() == 2  # 1 урок + «Сем.»


def test_delete_lesson_with_marks_is_refused_with_service_text(page, fake, monkeypatch):
    """Правило E: урок із відмітками не видаляється; причину (текст сервісу) показано інформаційним вікном."""
    fake.put_cell(S1, L1, "present", 5)
    page.reload_grid()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text, *a: shown.append(text))
    monkeypatch.setattr(page, "_confirm", lambda text, accept: pytest.fail("підтвердження замість відмови"))
    page._on_delete_lesson(L1)
    assert len(shown) == 1 and "Урок має оцінки чи позначки (1)" in shown[0] and "Спершу очистьте" in shown[0]
    assert page.grid_view.grid_model.column_of(L1) >= 0  # урок лишився в таблиці


def test_edit_lesson_dialog(page, qtbot):
    dialog = journal_dialogs.LessonDialog(1, page._api_factory, 1, page._lesson(L1))
    qtbot.addWidget(dialog)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("lab"))
    dialog.topic_edit.setText("  Практична  ")
    dialog._on_submit()
    assert dialog.result_info.lesson_type == "lab" and dialog.result_info.topic == "Практична"


def test_lesson_dialog_shows_service_error(page, qtbot):
    dialog = journal_dialogs.LessonDialog(1, page._api_factory, 1)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.date_edit.setDate(dialog.date_edit.date().addYears(-10))
    dialog._on_submit()
    assert dialog.error_label.isVisible()
    assert dialog.result_info is None


# --- сторінка ---

def test_semester_switch_shows_empty_state(page):
    page.semester_buttons[2].click()
    assert page.content_stack.currentIndex() == 1
    assert page.empty_label.text() == "Уроків у цьому семестрі ще немає"
    assert page.empty_lesson_btn.isVisible()


def test_no_students_empty_state(make_page):
    service = FakeJournalService([])
    service.add_lesson(date(2025, 9, 2))
    page = make_page(service)
    assert page.empty_label.text() == "У класі немає учнів"


def test_list_view_and_empty_list(page, fake):
    page.show_list()
    assert page.stack.currentIndex() == 0 and page.list_stack.currentIndex() == 0
    fake.journals.clear()
    page.show_list()
    assert page.list_stack.currentIndex() == 1


def test_new_journal_dialog_without_candidates_shows_hint(page, qtbot):
    dialog = journal_dialogs.NewJournalDialog(1, page._api_factory)
    qtbot.addWidget(dialog)
    assert not dialog.submit_button.isEnabled()
    assert "Спершу створіть клас" in dialog.hint_label.text()


def test_new_journal_dialog_creates(page, fake, qtbot):
    fake.candidates = [
        JournalCandidate(2, "10-Б", "2025-2026", 1, "Математика"),
        JournalCandidate(2, "10-Б", "2025-2026", 2, "Фізика"),
    ]
    dialog = journal_dialogs.NewJournalDialog(1, page._api_factory)
    qtbot.addWidget(dialog)
    assert dialog.subject_combo.count() == 2
    dialog.subject_combo.setCurrentIndex(1)
    dialog._on_submit()
    assert dialog.result_info.subject_name == "Фізика"


def test_ui_does_not_import_forbidden_layers():
    from pathlib import Path

    root = Path(journals_page.__file__).parent
    for name in ("journals_page.py", "journal_grid.py", "journal_dialogs.py"):
        text = (root / name).read_text(encoding="utf-8")
        for bad in ("import sqlalchemy", "from sqlalchemy", "journal.models", "journal.repositories"):
            assert bad not in text, (name, bad)


def test_delete_lesson_with_fresh_keyboard_marks_is_refused(page, fake, monkeypatch):
    """Оцінки, введені щойно без перезавантаження, теж захищають урок (простого підтвердження немає)."""
    view = page.grid_view
    column = view.grid_model.column_of(L1)
    view.setCurrentIndex(view.grid_model.index(0, column))
    type_text(view, "7")
    view.setCurrentIndex(view.grid_model.index(1, column))
    type_text(view, "н")
    assert len(fake.calls_of("set_cell")) == 2
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text, *a: shown.append(text))
    monkeypatch.setattr(page, "_confirm", lambda text, accept: pytest.fail("простий діалог замість відмови"))
    page._on_delete_lesson(L1)  # без reload_grid()
    assert len(shown) == 1 and "(2)" in shown[0]
    assert len(fake.calls_of("delete_lesson")) == 1  # відмову дає сервіс, а не інтерфейс


def test_returning_to_journals_page_refreshes_open_grid(page, fake):
    """Повернення на сторінку оновлює відкритий журнал (дані могли змінитися на сторінці «Класи»)."""
    fake.put_cell(S2, L1, "present", 9)  # змінено «десь іще», таблиця ще не знає
    column = page.grid_view.grid_model.column_of(L1)
    assert page.grid_view.grid_model.cell(1, column).grade is None
    page.refresh()
    assert page.grid_view.grid_model.cell(1, column).grade == 9

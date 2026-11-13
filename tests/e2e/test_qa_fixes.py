"""Перевірки виправлень fix/qa-findings на справжньому вікні: Налаштування зі скролом, довгі назви, підказки."""
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService
from journal.ui.classes_page import _ClassCard
from journal.ui.journal_dialogs import NewJournalDialog
from journal.ui.journals_page import _JournalCard, default_api_factory
from journal.ui.widgets import ElidedLabel
from tests.e2e.test_qa_scenarios import STUDENTS, make_class, make_journal, make_lesson, open_nav


@pytest.mark.parametrize("size", [(1280, 800), (1100, 700)])
def test_settings_page_scrolls_instead_of_squeezing(window, qtbot, size):
    window.resize(*size)
    open_nav(window, 2)
    card = window.semesters_card
    lines = [f"9-А · Алгебра — {n:02d}.01.2027" for n in range(1, 11)] + ["і ще 3", "рядок", "рядок"]
    card.error.setText("\n".join(lines))
    card.error.show()
    qtbot.wait(50)
    scroll = window.settings_scroll
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    for combo in (card.s1_start, card.s1_end, card.s2_start, card.s2_end):
        assert combo.height() >= combo.sizeHint().height()
    assert card.save_button.height() >= card.save_button.sizeHint().height()
    assert card.error.height() >= card.error.heightForWidth(card.error.width())


def test_card_titles_elide_and_columns_stay_equal(window, teacher, session, qtbot):
    tid = teacher.id
    long_class = make_class(session, tid, "11-А" + "Б" * 16)
    for name in ("5-А", "6-Б"):
        make_class(session, tid, name)
    open_nav(window, 0)
    window.classes_page.show_list()
    qtbot.wait(50)
    cards = window.classes_page.scroll.widget().findChildren(_ClassCard)
    assert len(cards) == 3
    assert len({c.width() for c in cards}) == 1
    assert window.classes_page.scroll.horizontalScrollBar().maximum() == 0
    assert window.classes_page.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    make_journal(session, tid, long_class.id, "Алгебра")
    for name in ("5-А", "6-Б"):
        cid = next(c.id for c in ClassService(session).list_classes(tid) if c.name == name)
        make_journal(session, tid, cid, "Геометрія")
    open_nav(window, 1)
    window.journals_page.show_list()
    qtbot.wait(50)
    jcards = window.journals_page.scroll.widget().findChildren(_JournalCard)
    assert len(jcards) == 3 and len({c.width() for c in jcards}) == 1
    assert window.journals_page.scroll.horizontalScrollBar().maximum() == 0
    assert window.journals_page.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert all(c.findChildren(ElidedLabel) for c in jcards)


def test_grid_header_tooltips_and_classes_table_tooltip(window, teacher, session):
    tid = teacher.id
    long_name = "Дуже-Довгопрізвищенко Олександр-Миколайович Іванович"
    c9 = make_class(session, tid, "9-А", students=[long_name, STUDENTS[0], STUDENTS[1]])
    sid = {s.full_name: s.id for s in ClassService(session).list_students(tid, c9.id)}
    alg = make_journal(session, tid, c9.id, "Алгебра")
    lesson = make_lesson(session, tid, alg.id, date(2026, 11, 10))
    # учень без записів при вибутті видаляється, тому спершу ставимо оцінку
    JournalService(session).set_cell(tid, lesson.id, sid[STUDENTS[1]], "present", 8, None)
    ClassService(session).set_student_archived(tid, sid[STUDENTS[1]], True)
    open_nav(window, 1)
    window.journals_page.open_journal(alg.id)
    model = window.journals_page.grid_view.grid_model
    tips = {
        student.full_name: model.headerData(row, Qt.Orientation.Vertical, Qt.ItemDataRole.ToolTipRole)
        for row, student in enumerate(model.students)
    }
    assert tips[long_name] == long_name
    assert tips[STUDENTS[1]] == f"{STUDENTS[1]}\nУчень вибув — лише перегляд"
    assert window.journals_page.grid_view.verticalHeader().textElideMode() == Qt.TextElideMode.ElideRight

    open_nav(window, 0)
    window.classes_page.open_class(c9.id)
    table = window.classes_page.table
    names = {table.item(r, 1).text(): table.item(r, 1).toolTip() for r in range(table.rowCount())}
    assert names[long_name] == long_name


def test_archived_delete_tooltip_empty_grid_hint_and_new_journal_close(window, teacher, session, qtbot):
    tid = teacher.id
    c9 = make_class(session, tid, "9-А")  # без учнів
    j = make_journal(session, tid, c9.id, "Алгебра")
    open_nav(window, 1)
    page = window.journals_page
    page.open_journal(j.id)
    assert page.empty_label.text() == "У класі немає учнів"
    assert not page.empty_hint.isHidden()
    assert "«Класи»" in page.empty_hint.text()

    ClassService(session).import_students(tid, c9.id, STUDENTS[0])
    ClassService(session).set_class_archived(tid, c9.id, True)
    page.open_journal(j.id)
    assert not page.delete_journal_action.isEnabled()
    assert page.delete_journal_action.toolTip() == "Журнал архівного класу не можна видалити"
    assert page.delete_journal_action.parent().toolTipsVisible()

    # вікно «Новий журнал», коли створювати нічого: є кнопка «Закрити»
    dialog = NewJournalDialog(tid, default_api_factory)
    qtbot.addWidget(dialog)
    close = [b for b in dialog.findChildren(QPushButton) if b.text() == "Закрити"]
    assert len(close) == 1
    dialog.show()
    close[0].click()
    assert not dialog.isVisible()

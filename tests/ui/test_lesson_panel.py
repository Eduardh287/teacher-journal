"""Тести етапу 5.1: панель «Проведені уроки», видалення журналу з вмістом, нотатки рецензії PR #9."""
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from journal.services.class_service import default_school_year
from journal.services.journal_types import JournalError, LessonInfo
from journal.ui import journals_page
from journal.ui.journal_dialogs import DeleteJournalDialog, DeleteLessonDialog, LessonDialog
from journal.ui.lesson_panel import NO_TOPIC_TEXT, lesson_row_text
from tests.fakes.fake_journal_service import FakeJournalService
from tests.ui.conftest import type_text
from tests.ui.test_journal_grid import L1, L2, S1, skip_if_vacation


def rows(page):
    """Зміст панелі: [(№, дата, тема)] за рядками."""
    table = page.lesson_panel.table
    return [tuple(table.item(r, c).text() for c in range(3)) for r in range(table.rowCount())]


def click_row(page, row):
    from PySide6.QtTest import QTest

    table = page.lesson_panel.table
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualItemRect(table.item(row, 2)).center())


# --- вміст і нумерація ---

def test_panel_rows_and_numbers(page):
    assert rows(page) == [("1", "02.09", NO_TOPIC_TEXT), ("2", "09.09", "Контрольна робота: Квадратні рівняння")]


def test_same_date_lessons_numbered_by_id(make_page):
    service = FakeJournalService(["А Б"])
    first = service.add_lesson(date(2025, 9, 2), "regular", "Перший")
    second = service.add_lesson(date(2025, 9, 2), "regular", "Другий")
    service.add_lesson(date(2025, 9, 1), "regular", "Раніше")
    page = make_page(service)
    assert [r[2] for r in rows(page)] == ["Раніше", "Перший", "Другий"]
    assert [lesson.id for lesson in page.grid_view.grid_model.lessons][1:] == [first, second]


def test_row_text_for_all_types():
    d = date(2025, 9, 2)
    assert lesson_row_text(LessonInfo(1, d, 1, "regular", "Дроби", 0)) == "Дроби"
    assert lesson_row_text(LessonInfo(1, d, 1, "regular", None, 0)) == ""
    assert lesson_row_text(LessonInfo(1, d, 1, "test", "Дроби", 0)) == "Контрольна робота: Дроби"
    assert lesson_row_text(LessonInfo(1, d, 1, "test", None, 0)) == "Контрольна робота"
    assert lesson_row_text(LessonInfo(1, d, 1, "lab", "Маятник", 0)) == "Лабораторна робота: Маятник"
    assert lesson_row_text(LessonInfo(1, d, 1, "lab", None, 0)) == "Лабораторна робота"
    assert lesson_row_text(LessonInfo(1, d, 1, "independent", "Дроби", 0)) == "Самостійна робота: Дроби"
    assert lesson_row_text(LessonInfo(1, d, 1, "independent", None, 0)) == "Самостійна робота"


def test_placeholder_is_italic_and_typed_row_is_tinted(page):
    table = page.lesson_panel.table
    assert table.item(0, 2).font().italic()
    assert not table.item(1, 2).font().italic()
    assert table.item(0, 2).background().style() == Qt.BrushStyle.NoBrush
    assert table.item(1, 2).background().style() != Qt.BrushStyle.NoBrush


def test_header_tooltip_has_number(page):
    model = page.grid_view.grid_model
    tip = model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert tip.startswith("Урок № 2 · 09.09.2025 · Контрольна робота")
    assert tip.endswith("\nКвадратні рівняння")
    assert "Урок № 1" in model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)


# --- взаємодія з таблицею ---

def test_row_click_selects_grid_column_keeping_row(page):
    view = page.grid_view
    view.select_cell(1, 0)
    click_row(page, 1)
    index = view.currentIndex()
    assert (index.row(), index.column()) == (1, 1)
    assert page.lesson_panel.selected_lesson_id() == L2


def test_grid_navigation_moves_panel_highlight(page, qtbot):
    page.grid_view.select_cell(0, 0)
    assert page.lesson_panel.selected_lesson_id() == L1
    qtbot.keyClick(page.grid_view, Qt.Key.Key_Tab)
    assert page.lesson_panel.selected_lesson_id() == L2
    assert [i.row() for i in page.lesson_panel.table.selectionModel().selectedRows()] == [1]


def test_panel_does_not_steal_focus(page):
    assert page.lesson_panel.table.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_double_click_opens_dialog_with_topic_focus_and_topic_is_updated(page, fake, monkeypatch):
    seen = {}

    class AutoDialog(LessonDialog):
        def __init__(self, *args, **kwargs):
            seen["focus_topic"] = kwargs.get("focus_topic")
            super().__init__(*args, **kwargs)
            seen["focus_widget"] = self.focusWidget()
            self.topic_edit.setText("Нова тема")

        def exec(self):
            self._on_submit()
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(journals_page, "LessonDialog", AutoDialog)
    page.lesson_panel.table.cellDoubleClicked.emit(0, 2)
    assert seen["focus_topic"] is True
    assert seen["focus_widget"] is not None
    assert rows(page)[0][2] == "Нова тема"


def test_lesson_dialog_focus_topic_selects_text(page, qtbot):
    dialog = LessonDialog(1, page._api_factory, 1, page._lesson(L2), focus_topic=True)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.focusWidget() is dialog.topic_edit
    assert dialog.topic_edit.selectedText() == "Квадратні рівняння"


def test_header_double_click_does_not_force_topic_focus(page, monkeypatch):
    seen = {}

    class SpyDialog(LessonDialog):
        def __init__(self, *args, **kwargs):
            seen["focus_topic"] = kwargs.get("focus_topic")
            super().__init__(*args, **kwargs)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(journals_page, "LessonDialog", SpyDialog)
    page.grid_view.lesson_edit_requested.emit(L1)
    assert seen["focus_topic"] is False


def test_double_click_on_any_cell_requests_edit_of_that_lesson(page, qtbot):
    from journal.ui.lesson_panel import LessonPanel

    panel = LessonPanel()  # окрема панель: сторінка відкрила б справжній діалог
    qtbot.addWidget(panel)
    panel.set_lessons(page.grid_view.grid_model.lessons, read_only=False)
    with qtbot.waitSignal(panel.lesson_edit_requested) as edit:
        panel.table.cellDoubleClicked.emit(1, 0)
    assert edit.args == [L2]


# --- синхронізація ---

def test_ctrl_n_adds_and_highlights_row(make_page):
    today = skip_if_vacation()
    service = FakeJournalService(["А Б", "В Г"], school_year=default_school_year(today))
    service.add_lesson(date(int(service.journal.school_year[:4]), 9, 1), "regular", "Перший")
    page = make_page(service)
    assert len(rows(page)) == 1
    page.new_lesson_shortcut.activated.emit()
    new_id = service.lessons[-1]["id"]
    assert len(rows(page)) == 2
    assert page.lesson_panel.selected_lesson_id() == new_id


def test_delete_removes_row(page, fake, monkeypatch):
    monkeypatch.setattr(page, "_confirm", lambda text, accept: True)
    page._on_delete_lesson(L1)
    assert rows(page) == [("1", "09.09", "Контрольна робота: Квадратні рівняння")]


def test_semester_switch_replaces_rows(page, fake):
    fake.add_lesson(date(2026, 2, 3), "lab", "Маятник")
    page.reload_grid()
    assert len(rows(page)) == 2
    page.semester_buttons[2].click()
    assert rows(page) == [("1", "03.02", "Лабораторна робота: Маятник")]
    assert page.lesson_panel.selected_lesson_id() == page.grid_view.grid_model.lessons[0].id


def test_archived_class_panel_is_editable(make_page, qtbot):
    """В архівному журналі панель дозволяє редагувати урок (рішення автора)."""
    service = FakeJournalService(["Коваленко Олена"], class_archived=True)
    service.add_lesson(date(2025, 9, 2), "regular", "Дроби")
    page = make_page(service)
    panel = page.lesson_panel
    assert panel.isVisible() and len(rows(page)) == 1
    # Від'єднуємо сторінку, щоб не відкрився справжній модальний діалог, і ловимо сигнал самі.
    panel.lesson_edit_requested.disconnect()
    emitted = []
    panel.lesson_edit_requested.connect(emitted.append)
    panel.table.cellDoubleClicked.emit(0, 2)
    assert emitted == [page.grid_view.grid_model.lessons[0].id]
    click_row(page, 0)
    assert panel.selected_lesson_id() == page.grid_view.grid_model.lessons[0].id


def test_toggle_hides_and_shows_panel(page):
    assert page.topics_btn.isChecked() and page.lesson_panel.isVisible()
    page.topics_btn.click()
    assert not page.lesson_panel.isVisible()
    page.topics_btn.click()
    assert page.lesson_panel.isVisible()


def test_panel_repopulated_on_theme_refresh(page):
    page.refresh_icons()
    assert len(rows(page)) == 2
    assert page.lesson_panel.selected_lesson_id() == L1


# --- нотатки рецензії PR #9 ---

def test_refresh_falls_back_to_list_when_grid_fails(page, fake):
    fake.fail_next = JournalError("Журнал не знайдено")
    page.refresh()
    assert page.stack.currentIndex() == 0


def test_refresh_keeps_current_cell(page):
    page.grid_view.select_cell(1, 1)
    page.refresh()
    index = page.grid_view.currentIndex()
    assert (index.row(), index.column()) == (1, 1)


def test_reload_falls_back_to_first_cell_when_lesson_gone(page, monkeypatch):
    monkeypatch.setattr(page, "_confirm", lambda text, accept: True)
    page.grid_view.select_cell(1, 0)
    page._on_delete_lesson(L1)
    index = page.grid_view.currentIndex()
    assert (index.row(), index.column()) == (0, 0)


def test_pending_one_committed_before_delete_dialog(page, fake, monkeypatch):
    view = page.grid_view
    view.select_cell(0, view.grid_model.column_of(L1))
    type_text(view, "1")
    assert fake.calls_of("set_cell") == []
    seen = {}

    def fake_exec(self):
        seen["sets"] = len(fake.calls_of("set_cell"))
        seen["count"] = self.lesson.entry_count
        seen["disabled_at_start"] = not self.delete_button.isEnabled()
        self.confirm_edit.setText("видалити")
        seen["enabled_after_word"] = self.delete_button.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(DeleteLessonDialog, "exec", fake_exec)
    monkeypatch.setattr(page, "_confirm", lambda text, accept: pytest.fail("простий діалог замість захищеного"))
    page._on_delete_lesson(L1)
    assert seen == {"sets": 1, "count": 1, "disabled_at_start": True, "enabled_after_word": True}
    assert fake.calls_of("delete_lesson") == []


def test_pending_one_committed_before_edit_dialog(page, fake, monkeypatch):
    view = page.grid_view
    view.select_cell(0, 0)
    type_text(view, "1")
    seen = {}

    class SpyDialog(LessonDialog):
        def exec(self):
            seen["sets"] = len(fake.calls_of("set_cell"))
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(journals_page, "LessonDialog", SpyDialog)
    page._on_edit_lesson(L1)
    assert seen == {"sets": 1}


# --- видалення журналу ---

def test_delete_empty_journal_uses_simple_confirm(make_page, monkeypatch):
    service = FakeJournalService(["А Б"])
    page = make_page(service)
    asked = []
    monkeypatch.setattr(page, "_confirm", lambda text, accept: asked.append(text) or True)
    monkeypatch.setattr(DeleteJournalDialog, "exec", lambda self: pytest.fail("типізований діалог для порожнього"))
    page._on_delete_journal()
    assert len(asked) == 1
    assert service.calls_of("delete_journal") == [("delete_journal", 1, False)]
    assert page.stack.currentIndex() == 0


def test_delete_journal_with_lessons_needs_typed_word(page, fake, monkeypatch):
    fake.put_cell(S1, L1, "present", 5)
    fake.add_lesson(date(2026, 2, 3))  # урок II семестру теж рахується
    seen = {}

    def fake_exec(self):
        seen["count"] = self.lesson_count
        seen["initially"] = self.delete_button.isEnabled()
        self.confirm_edit.setText("щось інше")
        seen["wrong"] = self.delete_button.isEnabled()
        self.confirm_edit.setText("Видалити")
        seen["ok"] = self.delete_button.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteJournalDialog, "exec", fake_exec)
    monkeypatch.setattr(page, "_confirm", lambda text, accept: pytest.fail("простий діалог замість захищеного"))
    page._on_delete_journal()
    assert (seen["count"], seen["initially"], seen["wrong"], seen["ok"]) == (3, False, False, True)
    assert fake.calls_of("delete_journal") == [("delete_journal", 1, True)]
    assert fake.lessons == [] and fake.cells == {}
    assert page.stack.currentIndex() == 0


def test_delete_journal_dialog_text(page, qtbot):
    info = page._grid.journal
    dialog = DeleteJournalDialog(info, 3)
    qtbot.addWidget(dialog)
    from PySide6.QtWidgets import QLabel

    texts = " ".join(w.text() for w in dialog.findChildren(QLabel))
    assert "Журнал «9-А · Математика» містить уроків: 3." in texts
    assert "безповоротно видалено всі уроки, відмітки та оцінки" in texts
    assert "введіть «видалити»" in texts


def test_delete_journal_cancel_deletes_nothing(page, fake, monkeypatch):
    monkeypatch.setattr(DeleteJournalDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    page._on_delete_journal()
    assert fake.calls_of("delete_journal") == []
    assert len(fake.lessons) == 2
    assert page.stack.currentIndex() == 1


def test_delete_journal_uses_fresh_lesson_count(page, fake, monkeypatch):
    """Уроки додано «десь іще» після завантаження таблиці — кількість береться зі свіжого списку."""
    fake.add_lesson(date(2025, 10, 7))
    counts = []
    monkeypatch.setattr(
        DeleteJournalDialog, "exec", lambda self: counts.append(self.lesson_count) or QDialog.DialogCode.Rejected
    )
    page._on_delete_journal()
    assert counts == [3]

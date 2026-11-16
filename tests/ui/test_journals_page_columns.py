"""Етап 6, рядок B: стовпчики «Тем»/«Зош», підсумкові «Сем.»/«Річна», «н/а», ручні оцінки, меню й д/з.

Працює лише з фейковим сервісом; модальні вікна підмінюємо.
"""
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from journal.services.grid_text import computed_text
from journal.services.journal_types import ComputedCell, GridColumn
from journal.ui import journals_page
from journal.ui.journal_grid import computed_tooltip
from tests.ui.conftest import type_text

L1, L2 = 1, 2
S1, S2, S_ARCH = 1, 2, 3
R1, R2, R_ARCH = 0, 1, 2  # рядки таблиці


def col(page, kind, column_id=None) -> int:
    index = page.grid_view.grid_model.column_index(GridColumn(kind, column_id))
    assert index >= 0, (kind, column_id)
    return index


def kinds(page) -> list[str]:
    return [c.kind for c in page.grid_view.grid_model.columns]


def text_at(page, row, column) -> str:
    model = page.grid_view.grid_model
    return model.data(model.index(row, column))


def tip_at(page, row, column) -> str:
    model = page.grid_view.grid_model
    return model.data(model.index(row, column), Qt.ItemDataRole.ToolTipRole)


def overrides(fake):
    return fake.calls_of("set_override")


@pytest.fixture
def themed(make_page, fake):
    """I семестр: уроки 02.09 і 09.09; оцінки Олени 7 і 8 → тематична 8 (7,5 → 8); Іван без оцінок."""
    fake.put_cell(S1, L1, "present", 7)
    fake.put_cell(S1, L2, "present", 8)
    tem = fake.add_column("thematic", L2)
    page = make_page(fake)
    return page, tem


# --- розкладка стовпців ---

def test_columns_order_and_headers(make_page, fake):
    nb = fake.add_column("notebook", L2)
    tem = fake.add_column("thematic", L2)
    page = make_page(fake)
    assert kinds(page) == ["lesson", "lesson", "notebook", "thematic", "semester"]  # за однакової дати: зошит → тематична
    model = page.grid_view.grid_model
    assert model.headerData(col(page, "thematic", tem), Qt.Orientation.Horizontal) == "Тем\n1"
    assert model.headerData(col(page, "notebook", nb), Qt.Orientation.Horizontal) == "Зош\n1"
    assert model.headerData(col(page, "semester"), Qt.Orientation.Horizontal) == "Сем."


def test_second_semester_has_semester_and_annual(make_page, fake):
    fake.add_lesson(date(2026, 2, 10))
    page = make_page(fake)
    page._on_semester_clicked(2)
    assert kinds(page) == ["lesson", "semester", "annual"]
    model = page.grid_view.grid_model
    assert model.headerData(col(page, "annual"), Qt.Orientation.Horizontal) == "Річна"


# --- автоматичні значення ---

def test_thematic_auto_half_up_and_tooltip(themed):
    page, tem = themed
    c = col(page, "thematic", tem)
    assert text_at(page, R1, c) == "8"
    assert tip_at(page, R1, c) == "Середнє 7,50 (2 оцінки) → 8"
    cell = page.grid_view.grid_model.computed_cell(R1, c)
    assert not cell.is_manual


def test_thematic_without_grades_shows_na(themed):
    page, tem = themed
    c = col(page, "thematic", tem)
    assert text_at(page, R2, c) == "н/а"
    assert "немає оцінок за тему" in tip_at(page, R2, c)
    # семестрова без жодної оцінки теж н/а (н/а = 0)
    assert text_at(page, R2, col(page, "semester")) == "н/а"


def test_semester_follows_thematic_and_tooltip(themed):
    page, _ = themed
    s = col(page, "semester")
    assert text_at(page, R1, s) == "8"
    assert tip_at(page, R1, s).startswith("Середнє тематичних 8,00")


def test_na_counts_as_zero_in_semester(make_page, fake):
    """Тематичні н/а, 8, 10 → семестрова (0+8+10)/3 = 6."""
    t1 = fake.add_column("thematic", L1)  # за період оцінок немає → н/а
    fake.add_lesson(date(2025, 9, 16))
    fake.put_cell(S1, L2, "present", 8)
    fake.put_cell(S1, 3, "present", 10)
    t2 = fake.add_column("thematic", L2)
    t3 = fake.add_column("thematic", 3)
    page = make_page(fake)
    assert [text_at(page, R1, col(page, "thematic", t)) for t in (t1, t2, t3)] == ["н/а", "8", "10"]
    assert text_at(page, R1, col(page, "semester")) == "6"


def test_annual_na_is_zero(make_page, fake):
    fake.put_cell(S1, L1, "present", 8)
    fake.add_column("thematic", L2)
    fake.add_lesson(date(2026, 2, 10))
    page = make_page(fake)
    page._on_semester_clicked(2)
    a = col(page, "annual")
    assert text_at(page, R1, col(page, "semester")) == "н/а"  # у II семестрі немає тематичних
    assert text_at(page, R1, a) == "4"  # (8 + н/а=0) / 2
    assert "н/а" in tip_at(page, R1, a)
    assert text_at(page, R2, a) == "н/а"  # обидві н/а


def test_lesson_grade_updates_thematic_semester_in_row(themed):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R2, 0)
    type_text(view, "9")
    assert text_at(page, R2, c) == "9"
    assert text_at(page, R2, col(page, "semester")) == "9"
    assert len(page.grid_view.grid_model.computed) >= 4


# --- введення в обчислюваних клітинках ---

def test_digit_sets_manual_override(themed):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R2, c)
    type_text(view, "9")
    assert overrides(page_fake(page))[-1][2:] == (S2, ("thematic", tem), 9, False)
    cell = view.grid_model.computed_cell(R2, c)
    assert cell.is_manual and cell.value == 9
    assert text_at(page, R2, c) == "9"
    assert tip_at(page, R2, c).startswith("Виставлено вручну: 9")
    assert text_at(page, R2, col(page, "semester")) == "9"


def page_fake(page):
    return page._api_factory().__enter__()


@pytest.mark.parametrize(("second", "grade"), [("0", 10), ("1", 11), ("2", 12)])
def test_chain_in_computed_cell(themed, second, grade):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R2, c)
    type_text(view, "1")
    assert overrides(page_fake(page)) == []
    assert text_at(page, R2, c) == "1"
    type_text(view, second)
    assert len(overrides(page_fake(page))) == 1
    assert view.grid_model.computed_cell(R2, c).override == grade


def test_lone_one_commits_after_timeout_in_computed_cell(themed, qtbot):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R2, c)
    type_text(view, "1")
    qtbot.waitUntil(lambda: view.grid_model.computed_cell(R2, c) is not None and
                    view.grid_model.computed_cell(R2, c).override == 1, timeout=2000)


def test_n_key_sets_na_override(themed):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R1, c)
    type_text(view, "н")
    assert overrides(page_fake(page))[-1][2:] == (S1, ("thematic", tem), None, True)
    cell = view.grid_model.computed_cell(R1, c)
    assert cell.is_manual and cell.is_na
    assert text_at(page, R1, c) == "н/а"
    assert "Виставлено вручну: н/а" in tip_at(page, R1, c)
    assert text_at(page, R1, col(page, "semester")) == "н/а"  # н/а = 0 у середньому
    type_text(view, "н")  # повторне «н» нічого не змінює
    assert len(overrides(page_fake(page))) == 1


def test_n_key_on_semester_cell(themed):
    page, _ = themed
    view = page.grid_view
    s = col(page, "semester")
    view.select_cell(R1, s)
    type_text(view, "н")
    assert overrides(page_fake(page))[-1][3] == ("semester", 1)
    assert text_at(page, R1, s) == "н/а"


def test_delete_clears_override_and_idle_delete_is_noop(themed):
    page, tem = themed
    view = page.grid_view
    c = col(page, "thematic", tem)
    view.select_cell(R1, c)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert overrides(page_fake(page)) == []  # автоматичне значення — нічого очищати
    type_text(view, "5")
    assert text_at(page, R1, c) == "5"
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert overrides(page_fake(page))[-1][3:] == (("thematic", tem), None, False)
    assert text_at(page, R1, c) == "8"
    assert not view.grid_model.computed_cell(R1, c).is_manual


@pytest.mark.parametrize("text", ["х", "з", "["])
def test_marks_ignored_in_computed_cells(themed, text):
    page, tem = themed
    view = page.grid_view
    view.select_cell(R1, col(page, "thematic", tem))
    type_text(view, text)
    QTest.keyClick(view, Qt.Key.Key_F2)
    fake = page_fake(page)
    assert overrides(fake) == [] and fake.calls_of("set_cell") == []


def test_archived_student_computed_row_is_read_only(make_page, fake):
    fake.put_cell(S_ARCH, L1, "present", 6)  # вибулий має оцінку → тематична порахована
    tem = fake.add_column("thematic", L2)
    page = make_page(fake)
    view = page.grid_view
    c = col(page, "thematic", tem)
    assert text_at(page, R_ARCH, c) == "6"
    view.select_cell(R_ARCH, c)
    type_text(view, "9")
    type_text(view, "н")
    assert overrides(fake) == []


def test_failed_override_keeps_old_value_and_shows_banner(themed):
    page, tem = themed
    fake = page_fake(page)
    c = col(page, "thematic", tem)
    page.grid_view.select_cell(R2, c)
    from journal.services.journal_types import JournalError

    fake.fail_next = JournalError("Не вдалося")
    type_text(page.grid_view, "9")
    assert text_at(page, R2, c) == "н/а"
    assert page.banner.text() == "Не вдалося"


# --- «Зошит» ---

@pytest.fixture
def with_notebook(make_page, fake):
    fake.put_cell(S1, L1, "present", 7)
    nb = fake.add_column("notebook", L2)
    tem = fake.add_column("thematic", L2)
    return make_page(fake), nb, tem


def test_notebook_digit_and_delete(with_notebook):
    page, nb, tem = with_notebook
    view = page.grid_view
    c = col(page, "notebook", nb)
    assert text_at(page, R1, c) == ""
    view.select_cell(R1, c)
    type_text(view, "5")
    assert overrides(page_fake(page))[-1][3:] == (("notebook", nb), 5, False)
    assert text_at(page, R1, c) == "5"
    assert tip_at(page, R1, c) == "Оцінка за зошит — не враховується в середніх"
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert text_at(page, R1, c) == ""


def test_notebook_ignores_n_and_marks_and_is_not_counted(with_notebook):
    page, nb, tem = with_notebook
    view = page.grid_view
    c = col(page, "notebook", nb)
    view.select_cell(R1, c)
    type_text(view, "н")
    type_text(view, "х")
    assert overrides(page_fake(page)) == []
    type_text(view, "3")
    assert text_at(page, R1, col(page, "thematic", tem)) == "7"  # зошит у середніх не бере участі
    assert text_at(page, R1, col(page, "semester")) == "7"


# --- створення стовпчиків: діалог «Новий урок» і гарячі клавіші ---

def _run_dialog(monkeypatch, kind):
    """Підміняє модальний exec: вибирає тип у списку й тисне «Створити»."""
    from journal.ui import journals_page
    from PySide6.QtWidgets import QDialog

    seen = {}

    class AutoDialog(journals_page.LessonDialog):
        def exec(self):
            seen["after"] = self.after_lesson_id
            self.type_combo.setCurrentIndex(self.type_combo.findData(kind))
            self._on_submit()
            seen["error"] = self.error_label.text()
            return QDialog.DialogCode.Accepted if self.result_column is not None else QDialog.DialogCode.Rejected

    monkeypatch.setattr(journals_page, "LessonDialog", AutoDialog)
    return seen


def test_no_add_column_button(page):
    assert not hasattr(page, "add_column_btn")


def test_thematic_via_new_lesson_dialog_selects_it(page, fake, monkeypatch):
    seen = _run_dialog(monkeypatch, "thematic")
    page.grid_view.select_cell(R2, 0)
    page.new_lesson_btn.click()
    assert seen["after"] == L2
    assert fake.calls_of("create_column") == [("create_column", 1, "thematic", L2)]
    assert kinds(page) == ["lesson", "lesson", "thematic", "semester"]
    cur = page.grid_view.currentIndex()
    assert cur.column() == 2 and cur.row() == R2


def test_notebook_via_new_lesson_dialog(page, fake, monkeypatch):
    _run_dialog(monkeypatch, "notebook")
    page.new_lesson_btn.click()
    assert fake.calls_of("create_column") == [("create_column", 1, "notebook", L2)]
    assert "notebook" in kinds(page)


def test_duplicate_column_shows_service_text_in_banner(page, fake):
    page.add_column("thematic")
    page.add_column("thematic")
    assert page.banner.text() == "Після цього уроку вже є такий стовпчик"
    assert kinds(page).count("thematic") == 1


@pytest.mark.parametrize(
    ("key", "mods", "kind"),
    [
        (Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier, "thematic"),
        (Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, "notebook"),
    ],
)
def test_shortcuts_create_columns(page, fake, key, mods, kind):
    page.grid_view.setFocus()
    QTest.keyClick(page.grid_view, key, mods)
    assert fake.calls_of("create_column") == [("create_column", 1, kind, L2)]


# --- меню заголовків ---

class _Action:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


def pick(monkeypatch, text):
    """Підміна QMenu у таблиці: модальне меню не відкривається; «вибирає» пункт із текстом text.

    Повертає список показаних пунктів (заповнюється при відкритті меню)."""
    from journal.ui import journal_grid

    shown = []

    class FakeMenu:
        def __init__(self, *_):
            self.items = []

        def addAction(self, label, callback):
            action = _Action(label)
            action.callback = callback
            self.items.append(action)
            return action

        def exec(self, *_):
            shown[:] = [a.text() for a in self.items]
            chosen = next((a for a in self.items if a.text() == text), None)
            if chosen is not None:
                chosen.callback()
            return chosen

    monkeypatch.setattr(journal_grid, "QMenu", FakeMenu)
    return shown


def open_header_menu(page, column):
    header = page.grid_view.horizontalHeader()
    pos = header.rect().topLeft()
    pos.setX(header.sectionViewportPosition(column) + 5)
    pos.setY(5)
    header.customContextMenuRequested.emit(pos)


def test_thematic_header_menu_has_move_and_delete(themed, monkeypatch):
    page, tem = themed
    shown = pick(monkeypatch, "—")
    open_header_menu(page, col(page, "thematic", tem))
    assert shown == ["Перемістити…", "Видалити"]


def test_lesson_header_menu_unchanged_and_finals_have_none(themed, monkeypatch):
    page, _ = themed
    shown = pick(monkeypatch, "—")
    open_header_menu(page, 0)
    assert shown == ["Редагувати урок", "Видалити урок"]
    shown.clear()
    open_header_menu(page, col(page, "semester"))
    assert shown == []


def test_move_column_via_header_menu(themed, monkeypatch):
    page, tem = themed
    fake = page_fake(page)
    pick(monkeypatch, "Перемістити…")
    asked = {}

    def get_item(parent, title, label, items, current, editable):
        asked.update(items=items, current=current)
        return items[0], True

    monkeypatch.setattr(QInputDialog, "getItem", get_item)
    open_header_menu(page, col(page, "thematic", tem))
    assert fake.calls_of("move_column") == [("move_column", tem, L1)]
    assert asked["current"] == 1 and len(asked["items"]) == 2
    assert kinds(page) == ["lesson", "thematic", "lesson", "semester"]


def test_move_column_cancelled(themed, monkeypatch):
    page, tem = themed
    pick(monkeypatch, "Перемістити…")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("", False))
    open_header_menu(page, col(page, "thematic", tem))
    assert page_fake(page).calls_of("move_column") == []


def test_delete_thematic_asks_confirm(themed, monkeypatch):
    page, tem = themed
    fake = page_fake(page)
    pick(monkeypatch, "Видалити")
    monkeypatch.setattr(journals_page, "confirm", lambda parent, text, accept: False)
    open_header_menu(page, col(page, "thematic", tem))
    assert fake.calls_of("delete_column") == []
    monkeypatch.setattr(journals_page, "confirm", lambda parent, text, accept: True)
    open_header_menu(page, col(page, "thematic", tem))
    assert fake.calls_of("delete_column") == [("delete_column", tem)]
    assert "thematic" not in kinds(page)


def test_delete_empty_notebook_asks_confirm(make_page, fake, monkeypatch):
    nb = fake.add_column("notebook", L2)
    page = make_page(fake)
    pick(monkeypatch, "Видалити")
    asked = []
    monkeypatch.setattr(journals_page, "confirm", lambda parent, text, accept: asked.append(text) or True)
    open_header_menu(page, col(page, "notebook", nb))
    assert len(asked) == 1
    assert "notebook" not in kinds(page)


def test_delete_notebook_with_grades_is_refused_with_service_text(with_notebook, monkeypatch):
    page, nb, _ = with_notebook
    fake = page_fake(page)
    fake.put_extra_grade(nb, S1, 6)
    page.reload_grid()
    pick(monkeypatch, "Видалити")
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text, *a: shown.append(text))
    monkeypatch.setattr(journals_page, "confirm", lambda parent, text, accept: pytest.fail("підтвердження замість відмови"))
    open_header_menu(page, col(page, "notebook", nb))
    assert shown == ["У стовпчику «Зошит» є оцінки (1) — його не можна видалити. Спершу очистьте їх."]
    assert "notebook" in kinds(page)


def test_panel_column_signals_reach_page(themed, monkeypatch):
    page, tem = themed
    fake = page_fake(page)
    monkeypatch.setattr(journals_page, "confirm", lambda parent, text, accept: True)
    page.lesson_panel.column_delete_requested.emit(tem)
    assert fake.calls_of("delete_column") == [("delete_column", tem)]


# --- домашнє завдання ---

def test_homework_edit_from_panel_saves_and_reloads(page, fake):
    page.lesson_panel.homework_edited.emit(L1, "§12, № 3-5")
    assert fake.calls_of("set_homework") == [("set_homework", L1, "§12, № 3-5")]
    assert page._lesson(L1).homework == "§12, № 3-5"
    tip = page.grid_view.grid_model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "Домашнє завдання: §12, № 3-5" in tip


def test_homework_error_shows_banner(page, fake):
    from journal.services.journal_types import JournalError

    fake.fail_next = JournalError("Домашнє завдання — не довше 500 символів")
    page.lesson_panel.homework_edited.emit(L1, "x")
    assert page.banner.text().startswith("Домашнє завдання")
    assert page._lesson(L1).homework is None


# --- чисті функції тексту ---

def test_plural_forms():
    from journal.services.grid_text import plural

    forms = ("оцінка", "оцінки", "оцінок")
    assert [plural(n, *forms) for n in (1, 2, 5, 11, 12, 21, 22, 25, 100)] == [
        "оцінка", "оцінки", "оцінок", "оцінок", "оцінок", "оцінка", "оцінки", "оцінок", "оцінок"
    ]


def test_computed_text_and_tooltips():
    na = ComputedCell(None, True, 0, 0, None, False)
    manual = ComputedCell(8, False, 15, 2, 9, False)
    assert computed_text("thematic", na) == "н/а"
    assert computed_text("thematic", manual) == "9"
    assert computed_text("thematic", None) == ""
    assert computed_text("notebook", ComputedCell(None, False, 0, 0, 5, False)) == "5"
    assert computed_tooltip("semester", na) == "н/а — немає тематичних оцінок"
    assert computed_tooltip("annual", na) == "н/а — немає семестрових оцінок"
    assert "Автоматично: 8" in computed_tooltip("thematic", manual)
    annual = ComputedCell(4, False, 8, 2, None, False)
    assert "н/а семестрова рахується як 0" in computed_tooltip("annual", annual)


def test_panel_order_matches_grid_order_for_same_day_lesson_after_thematic(make_page, fake):
    from datetime import date as _d

    from tests.fakes.fake_journal_service import FakeJournalService

    f = FakeJournalService(["Коваленко Олена"])
    a = f.add_lesson(_d(2026, 9, 2))
    f.add_column("thematic", a)
    f.add_lesson(_d(2026, 9, 2))  # той самий день, створений після тематичної
    page = make_page(f)
    grid_kinds = [c.kind for c in page.grid_view.grid_model.columns if c.kind in ("lesson", "thematic")]
    assert grid_kinds == ["lesson", "thematic", "lesson"]
    from journal.services.journal_types import LessonInfo

    panel_order = [
        ("lesson" if isinstance(r, LessonInfo) else r.kind, r.id) for r in page.lesson_panel._rows
    ]
    grid_order = [(c.kind, c.id) for c in page.grid_view.grid_model.columns if c.kind in ("lesson", "thematic", "notebook")]
    assert panel_order == grid_order

"""Наскрізні сценарії S1–S10 (docs/specs/qa-plan.md, агент B): справжні сторінки, діалоги й сервіси на journal_test.

Імена учнів вигадані. Знахідки QA-B1..B3 виправлено в `fix/qa-findings`, їхні сценарії тепер звичайні тести.
"""
from datetime import date

import pytest
from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
)
from sqlalchemy import func, select

from journal.models import Lesson, LessonEntry, Student, Subject, Teacher
from journal.services.class_service import ClassError, ClassNotFound, ClassService
from journal.services.journal_service import JournalService
from journal.services.journal_types import JournalError, JournalNotFound, LessonNotFound, SemesterConflict
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries
from journal.services.rollover_service import RolloverService
from journal.services.settings_service import SettingsService
from journal.ui import theme
from journal.ui.class_dialogs import ClassDialog, ImportStudentsDialog, StudentDialog
from journal.ui.classes_page import _ClassCard
from journal.ui.journal_dialogs import (
    CommentDialog,
    DeleteJournalDialog,
    JournalSettingsDialog,
    LessonDialog,
    NewJournalDialog,
)
from journal.ui.journals_page import _JournalCard, default_api_factory
from journal.ui.rollover_dialog import RolloverDialog, item_text, maybe_run_rollover
from tests.ui.conftest import type_text

SURNAMES = [
    "Демченко", "Тестовий", "Коваленко", "Шевченко", "Мельник", "Бондаренко", "Ткаченко", "Кравчук",
    "Олійник", "Поліщук", "Лисенко", "Савчук", "Мороз", "Гончар", "Руденко", "Петренко", "Іваненко",
    "Захарченко", "Войтенко", "Дем'яненко",
]
FIRST_NAMES = ["Олена", "Іван", "Марія", "Андрій", "Софія", "Тарас", "Оксана", "Максим", "Дарина", "Назар"]
STUDENTS = [f"{SURNAMES[i % 20]} {FIRST_NAMES[(3 * i + i // 20) % 10]}" for i in range(40)]
assert len(set(STUDENTS)) == 40
ALL_STUDENT_NAMES = set(STUDENTS)  # S10: жодне з цих імен не має потрапити в журнал помилок

YEAR = "2026-2027"
ENTER = Qt.Key.Key_Return


# ---------------------------------------------------------------------------
# Допоміжне
# ---------------------------------------------------------------------------


def button(parent, text: str) -> QPushButton:
    found = [b for b in parent.findChildren(QPushButton) if b.text() == text]
    assert len(found) == 1, f"кнопка «{text}»: знайдено {len(found)} серед {[b.text() for b in parent.findChildren(QPushButton)]}"
    return found[0]


def subject_id(session, name: str) -> int:
    return session.scalars(select(Subject.id).where(Subject.name == name)).one()


def make_class(session, teacher_id: int, name: str, year: str = YEAR, students: list[str] | None = None):
    service = ClassService(session)
    info = service.create_class(teacher_id, name, year)
    if students:
        service.import_students(teacher_id, info.id, "\n".join(students))
    return info


def make_journal(session, teacher_id: int, class_id: int, subject: str = "Алгебра"):
    return JournalService(session).create_journal(teacher_id, class_id, subject_id(session, subject))


def make_lesson(session, teacher_id: int, journal_id: int, d: date, kind: str = "regular", topic: str | None = None):
    return JournalService(session).create_lesson(teacher_id, journal_id, d, kind, topic)


def student_ids(session, teacher_id: int, class_id: int) -> dict[str, int]:
    return {s.full_name: s.id for s in ClassService(session).list_students(teacher_id, class_id)}


def confirm_with(text: str, seen: list | None = None):
    """Обробник QMessageBox із підтвердженням: перевіряє «Скасувати» за замовчуванням і натискає кнопку `text`."""

    def action(box: QMessageBox):
        assert isinstance(box, QMessageBox)
        if seen is not None:
            seen.append(box.text())
        assert box.defaultButton().text() == "Скасувати", "у підтвердженні за замовчуванням має бути «Скасувати»"
        assert box.escapeButton().text() == "Скасувати"
        target = next(b for b in box.buttons() if b.text() == text)
        target.click()

    return action


def typed_confirm(word: str):
    """Обробник діалогу з введенням слова: кнопка неактивна до слова, потім натискаємо її."""

    def action(dialog):
        delete = dialog.delete_button
        assert not delete.isEnabled()
        dialog.confirm_edit.setText("видали")  # неповне слово
        assert not delete.isEnabled()
        dialog.confirm_edit.setText(word)
        assert delete.isEnabled()
        delete.click()

    return action


def click_date_cell(table, row: int, column: int = 2):
    """Подвійний клік мишею по клітинці QTableWidget."""
    item = table.item(row, column)
    pos = table.visualItemRect(item).center()
    # як у справжньому подвійному кліку: перший клік вже виділив клітинку (QTest.mouseDClick сам по собі подію не дає)
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def grid_cells(session, teacher_id: int, journal_id: int, semester: int = 1):
    grid = JournalService(session).get_grid(teacher_id, journal_id, semester)
    return grid, grid.cells


def classes_cards(page) -> list:
    host = page.scroll.widget()
    return [] if host is None or page.list_stack.currentIndex() != 0 else host.findChildren(_ClassCard)


def journal_cards(page) -> list:
    host = page.scroll.widget()
    return [] if host is None or page.list_stack.currentIndex() != 0 else host.findChildren(_JournalCard)


def open_nav(window, row: int):
    window.nav.setCurrentRow(row)
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# S1. Клас → учні → імпорт → вибулий → журнал → Ctrl+N → введення з клавіатури
# ---------------------------------------------------------------------------


def test_s1_class_to_keyboard_entry(window, teacher, session, drive, qtbot, msgs):
    classes = window.classes_page
    journals = window.journals_page
    tid = teacher.id

    # --- клас ---
    assert classes.list_stack.currentIndex() == 1, "порожній стан сторінки «Класи»"

    def create_class(dlg):
        dlg.name_edit.setText("9-А")
        assert dlg.year_combo.currentText() == YEAR
        QTest.keyClick(dlg.name_edit, ENTER)  # Enter = «Створити»

    run = drive(create_class)
    button(classes.list_stack.widget(1), "Новий клас").click()
    run.check()
    assert not run.stayed_open
    assert [c.name for c in ClassService(session).list_classes(tid)] == ["9-А"]
    assert len(classes_cards(classes)) == 1

    class_id = ClassService(session).list_classes(tid)[0].id
    classes.open_class(class_id)
    assert classes.stack.currentIndex() == 1
    assert classes.detail_title.text() == f"9-А · {YEAR}"
    assert classes.students_stack.currentIndex() == 1, "порожній стан класу без учнів"

    # --- два учні: дубль (іншим регістром) відхиляється, «Додати ще», Enter ---
    def add_two(dlg):
        dlg.name_edit.setText(STUDENTS[0])
        button(dlg, "Додати ще").click()
        assert not dlg.note_label.isHidden() and STUDENTS[0] in dlg.note_label.text()
        assert dlg.name_edit.text() == ""
        dlg.name_edit.setText(STUDENTS[0].upper())
        button(dlg, "Додати").click()
        assert not dlg.error_label.isHidden() and "уже є" in dlg.error_label.text()
        assert dlg.isVisible(), "діалог лишається відкритим після помилки"
        dlg.name_edit.setText(STUDENTS[1])
        QTest.keyClick(dlg.name_edit, ENTER)  # Enter = «Додати»

    run = drive(add_two)
    classes.add_student_btn.click()
    run.check()
    assert not run.stayed_open
    assert len(classes._students) == 2 and classes.detail_subtitle.text() == "2 учні"

    # --- імпорт списком: номери, порожні рядки, дубль в існуючому (інший регістр) і дубль у списку ---
    pasted = [f"{i + 1}. {name}" for i, name in enumerate(STUDENTS[2:36])]
    pasted.insert(3, "")
    pasted.append(f"{STUDENTS[0].lower()}")
    pasted.append(f"\t{STUDENTS[5]}")

    def do_import(dlg):
        dlg.text_edit.setPlainText("\n".join(pasted))
        QTest.qWait(450)  # підказка оновлюється з затримкою 300 мс
        assert dlg.preview_label.text() == "Буде додано: 34 · дублікатів пропущено: 2", dlg.preview_label.text()
        assert dlg.submit_button.isEnabled()
        dlg.submit_button.click()

    run = drive(do_import)
    classes.import_btn.click()
    run.check()
    assert len(classes._students) == 36
    assert any(m[1] == "Імпорт завершено" for m in msgs)

    # --- учень без записів: «Прибрати» видаляє зі списку (підтвердження, за замовчуванням «Скасувати») ---
    victim = STUDENTS[35]
    classes.table.selectRow([s.full_name for s in classes._students].index(victim))
    run = drive(confirm_with("Прибрати"))
    classes.remove_student_btn.click()
    run.check()
    students = ClassService(session).list_students(tid, class_id)
    assert len(students) == 35 and victim not in {s.full_name for s in students}
    assert [s.position for s in students] == list(range(1, 36)), "номери 1..35 без прогалин"

    # --- журнал ---
    open_nav(window, 1)
    assert journals.list_stack.currentIndex() == 1, "порожній стан сторінки «Журнали»"

    def new_journal(dlg):
        assert dlg.class_combo.count() == 1 and dlg.class_combo.currentText() == f"9-А · {YEAR}"
        dlg.subject_combo.setCurrentIndex(dlg.subject_combo.findText("Алгебра"))
        QTest.keyClick(dlg.subject_combo, ENTER)  # Enter = «Створити»

    run = drive(new_journal)
    journals.new_journal_btn.click()
    run.check()
    assert journals.stack.currentIndex() == 1
    assert journals.title_label.text() == "9-А · Алгебра"
    assert journals.content_stack.currentIndex() == 1
    assert journals.empty_label.text() == "Уроків у цьому семестрі ще немає"
    journal_id = journals._journal_id

    # --- Ctrl+N: урок на сьогодні без діалогу ---
    window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is window)
    journals.empty_lesson_btn.setFocus()
    QTest.keyClick(journals.empty_lesson_btn, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    grid, _ = grid_cells(session, tid, journal_id)
    assert [(l.lesson_date, l.lesson_type) for l in grid.lessons] == [(date(2026, 11, 12), "regular")], "Ctrl+N"
    assert journals.content_stack.currentIndex() == 0

    def second_lesson(dlg):
        dlg.date_edit.setDate(QDate(2026, 11, 19))
        dlg.type_combo.setCurrentIndex(dlg.type_combo.findData("test"))
        dlg.topic_edit.setText("Квадратні рівняння")
        QTest.keyClick(dlg.topic_edit, ENTER)

    run = drive(second_lesson)
    journals.new_lesson_btn.click()
    run.check()
    assert len(journals.grid_view.grid_model.lessons) == 2

    # --- введення з клавіатури: перший стовпець ---
    view = journals.grid_view
    view.select_cell(0, 0)
    view.setFocus()

    def enter():
        QTest.keyClick(view, ENTER)

    def comment_dialog(text):
        def action(dlg):
            dlg.edit.setPlainText(text)
            button(dlg, "Зберегти").click()

        return action

    type_text(view, "5"); enter()                               # r0: 5
    type_text(view, "1"); type_text(view, "0"); enter()         # r1: 10
    type_text(view, "1"); type_text(view, "1"); enter()         # r2: 11
    type_text(view, "1"); type_text(view, "2"); enter()         # r3: 12
    type_text(view, "1"); qtbot.wait(200); enter()              # r4: самотня «1» → 1 через вікно ланцюжка
    type_text(view, "н"); enter()                               # r5: відсутній
    type_text(view, "х"); enter()                               # r6: хворіє
    type_text(view, "з"); enter()                               # r7: запізнився
    type_text(view, "з"); type_text(view, "9"); enter()         # r8: «з 9»
    type_text(view, "7"); QTest.keyClick(view, Qt.Key.Key_Delete); enter()   # r9: 7, потім Del → порожньо
    type_text(view, "н"); type_text(view, "н"); enter()         # r10: «н» двічі → знову присутній, порожньо
    run = drive(comment_dialog("Спізнився на 5 хв"))            # r11: лише коментар
    QTest.keyClick(view, Qt.Key.Key_F2)
    run.check()
    enter()
    type_text(view, "8")                                        # r12: 8 + коментар у першому стовпці
    run = drive(comment_dialog("Гарна відповідь"))
    QTest.keyClick(view, Qt.Key.Key_F2)
    run.check()
    QTest.keyClick(view, Qt.Key.Key_Tab)                        # → другий стовпець (КР)
    assert (view.currentIndex().row(), view.currentIndex().column()) == (12, 1)
    type_text(view, "9")
    QTest.keyClick(view, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)  # назад
    assert (view.currentIndex().row(), view.currentIndex().column()) == (12, 0)
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert view.currentIndex().row() == 11

    grid, cells = grid_cells(session, tid, journal_id)
    first, test_lesson = grid.lessons[0].id, grid.lessons[1].id

    def triple(row: int, lesson_id: int = first):
        c = cells.get((grid.students[row].id, lesson_id))
        return None if c is None else (c.attendance, c.grade, c.comment)

    assert triple(0) == ("present", 5, None)
    assert triple(1) == ("present", 10, None)
    assert triple(2) == ("present", 11, None)
    assert triple(3) == ("present", 12, None)
    assert triple(4) == ("present", 1, None)
    assert triple(5) == ("absent", None, None)
    assert triple(6) == ("sick", None, None)
    assert triple(7) == ("late", None, None)
    assert triple(8) == ("late", 9, None)
    assert triple(9) is None, "Del прибрав оцінку: рядок у БД зникає"
    assert triple(10) is None, "повторне «н» повертає присутність"
    assert triple(11) == ("present", None, "Спізнився на 5 хв")
    assert triple(12) == ("present", 8, "Гарна відповідь")
    assert triple(12, test_lesson) == ("present", 9, None)
    assert len(cells) == 12

    # --- вибулий: учень з відмітками позначається вибулим (архів), а не видаляється ---
    absent_student = grid.students[5]
    open_nav(window, 0)
    classes.open_class(class_id)
    classes.table.selectRow([s.full_name for s in classes._students].index(absent_student.full_name))
    run = drive(confirm_with("Позначити"))
    classes.remove_student_btn.click()
    run.check()
    withdrawn = {s.full_name: s for s in ClassService(session).list_students(tid, class_id)}[absent_student.full_name]
    assert withdrawn.archived and withdrawn.position == 0
    assert classes.table.item(len(classes._students) - 1, 0).text() == "вибув"

    open_nav(window, 1)  # повернення на «Журнали» оновлює відкритий журнал
    model = view.grid_model
    assert model.students[-1].archived and model.students[-1].full_name == absent_student.full_name
    assert model.headerData(len(model.students) - 1, Qt.Orientation.Vertical).startswith("вибув · ")
    last = len(model.students) - 1
    view.select_cell(last, 0)
    view.setFocus()
    before = dict(view.grid_model.cells)
    type_text(view, "5")
    QTest.keyClick(view, Qt.Key.Key_Delete)
    type_text(view, "н")
    assert view.grid_model.cells == before, "рядок вибулого лише для перегляду"
    _, cells_after = grid_cells(session, tid, journal_id)
    assert cells_after[(absent_student.id, first)].attendance == "absent"
    assert not [m for m in msgs if m[0] == "critical"]



# ---------------------------------------------------------------------------
# S2. Панель уроків: правка типу й теми, видалення уроку з оцінками, нумерація за семестрами
# ---------------------------------------------------------------------------


def panel_rows(panel) -> list[tuple[str, str, str]]:
    t = panel.table
    return [(t.item(r, 0).text(), t.item(r, 1).text(), t.item(r, 2).text()) for r in range(t.rowCount())]


def test_s2_lesson_panel(window, teacher, session, drive, qtbot, msgs):
    tid = teacher.id
    service = JournalService(session)
    school_class = make_class(session, tid, "9-А", students=STUDENTS[:3])
    journal = make_journal(session, tid, school_class.id)
    jid = journal.id
    l1 = make_lesson(session, tid, jid, date(2026, 9, 2), "regular", "Повторення")
    l2 = make_lesson(session, tid, jid, date(2026, 9, 9), "test", "Вхідна КР")
    l3 = make_lesson(session, tid, jid, date(2026, 9, 16))
    l4 = make_lesson(session, tid, jid, date(2026, 12, 3), "regular", "Підсумок семестру")
    l5 = make_lesson(session, tid, jid, date(2027, 1, 13), "regular", "Нова чверть")
    l6 = make_lesson(session, tid, jid, date(2027, 2, 10), "lab", "Практична")
    ids = student_ids(session, tid, school_class.id)
    first, second = ids[sorted(ids)[0]], ids[sorted(ids)[1]]
    service.set_cell(tid, l2.id, first, "present", 7, None)
    service.set_cell(tid, l2.id, second, "absent", None, None)

    journals = window.journals_page
    panel = journals.lesson_panel
    open_nav(window, 1)
    journals.open_journal(jid)
    assert journals._semester == 1

    # --- нумерація: у кожному семестрі з 1 ---
    assert panel_rows(panel) == [
        ("1", "02.09", "Повторення"),
        ("2", "09.09", "Контрольна робота: Вхідна КР"),
        ("3", "16.09", "тема не вказана"),
        ("4", "03.12", "Підсумок семестру"),
    ]
    # відкладена «1» (чекає другу цифру) підтверджується як оцінка 1 при перемиканні семестру
    journals.grid_view.select_cell(0, 0)
    journals.grid_view.setFocus()
    type_text(journals.grid_view, "1")
    journals.semester_buttons[2].click()
    assert journals._semester == 2
    _, cells = grid_cells(session, tid, jid)
    assert cells[(journals.grid_view.grid_model.students[0].id, l1.id)].grade == 1
    # Нумерація наскрізна за навчальний рік (рішення викладачки, етап 6): II семестр продовжує I.
    first_number = int(panel_rows(panel)[0][0])
    assert first_number > 1
    assert panel_rows(panel) == [
        (str(first_number), "13.01", "Нова чверть"),
        (str(first_number + 1), "10.02", "Лабораторна робота: Практична"),
    ]
    journals.semester_buttons[1].click()

    # --- правка: подвійний клік по темі → діалог із фокусом на темі; тип і тема змінюються ---
    def edit_l3(dlg):
        assert dlg.focusWidget() is dlg.topic_edit, "подвійний клік по темі: фокус на полі теми"
        assert dlg.topic_edit.text() == ""
        dlg.topic_edit.setText("Лінійні рівняння")
        dlg.type_combo.setCurrentIndex(dlg.type_combo.findData("test"))
        QTest.keyClick(dlg.topic_edit, ENTER)

    run = drive(edit_l3)
    click_date_cell(panel.table, 2)
    run.check()
    assert not run.stayed_open
    grid, _ = grid_cells(session, tid, jid)
    lesson3 = next(x for x in grid.lessons if x.id == l3.id)
    assert (lesson3.lesson_type, lesson3.topic) == ("test", "Лінійні рівняння")
    assert panel_rows(panel)[2] == ("3", "16.09", "Контрольна робота: Лінійні рівняння")
    assert panel.selected_lesson_id() == l3.id
    header = journals.grid_view.grid_model.headerData(2, Qt.Orientation.Horizontal)
    assert header == "16.09\nКР"

    # --- урок з оцінками не видаляється (рішення викладачки, етап 6): пояснення, урок лишається ---
    msgs.clear()
    panel.lesson_delete_requested.emit(l2.id)
    assert any(kind == "information" and "не можна видалити" in text for kind, _, text in msgs), msgs
    assert any(x.id == l2.id for x in grid_cells(session, tid, jid)[0].lessons)

    # після очищення клітинок урок стає порожнім і видаляється звичайним підтвердженням
    service = JournalService(session)
    for (sid, lid) in list(grid_cells(session, tid, jid)[1]):
        if lid == l2.id:
            service.set_cell(tid, l2.id, sid, "present", None, None)
    journals.reload_grid()
    run = drive(confirm_with("Видалити"))
    panel.lesson_delete_requested.emit(l2.id)
    run.check()
    grid, cells = grid_cells(session, tid, jid)
    assert l2.id not in [x.id for x in grid.lessons]
    assert session.scalar(select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id == l2.id)) == 0
    assert panel_rows(panel) == [
        ("1", "02.09", "Повторення"),
        ("2", "16.09", "Контрольна робота: Лінійні рівняння"),
        ("3", "03.12", "Підсумок семестру"),
    ], "після видалення нумерація без прогалин"

    # --- видалення уроку без оцінок: просте підтвердження, за замовчуванням «Скасувати» ---
    run = drive(confirm_with("Скасувати"))
    panel.lesson_delete_requested.emit(l4.id)
    run.check()
    assert any(x.id == l4.id for x in grid_cells(session, tid, jid)[0].lessons)
    run = drive(confirm_with("Видалити"))
    panel.lesson_delete_requested.emit(l4.id)
    run.check()
    assert l4.id not in [x.id for x in grid_cells(session, tid, jid)[0].lessons]

    # --- перенесення уроку в інший семестр: перемикається семестр, нумерація обох семестрів перераховується ---
    def move_to_january(dlg):
        dlg.date_edit.setDate(QDate(2027, 1, 20))
        QTest.keyClick(dlg.topic_edit, ENTER)

    run = drive(move_to_january)
    journals._on_edit_lesson(l1.id)
    run.check()
    assert journals._semester == 2, "після перенесення відкрито семестр, куди потрапив урок"
    # наскрізна нумерація за рік: номери ІІ семестру продовжують І
    first = int(panel_rows(panel)[0][0])
    assert panel_rows(panel) == [
        (str(first), "13.01", "Нова чверть"),
        (str(first + 1), "20.01", "Повторення"),
        (str(first + 2), "10.02", "Лабораторна робота: Практична"),
    ]
    assert panel.selected_lesson_id() == l1.id
    journals.semester_buttons[1].click()
    assert panel_rows(panel) == [("1", "16.09", "Контрольна робота: Лінійні рівняння")]
    assert l6.id and l5.id
    assert not [m for m in msgs if m[0] == "critical"]


# ---------------------------------------------------------------------------
# S3. Налаштування: II семестр із грудня переносить груднєвий урок; конфліктна зміна не зберігає нічого
# ---------------------------------------------------------------------------


def semester_of(session, lesson_id: int) -> int:
    return session.scalar(select(Lesson.semester).where(Lesson.id == lesson_id))


def test_s3_settings_semesters(window, teacher, session, qtbot, msgs):
    tid = teacher.id
    service = JournalService(session)
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:3])
    algebra = make_journal(session, tid, c9.id, "Алгебра")
    geometry = make_journal(session, tid, c9.id, "Геометрія")
    nov = make_lesson(session, tid, algebra.id, date(2026, 11, 10))
    dec = make_lesson(session, tid, algebra.id, date(2026, 12, 10))
    jan = make_lesson(session, tid, algebra.id, date(2027, 1, 14))
    dec_geo = make_lesson(session, tid, geometry.id, date(2026, 12, 2))
    geo_nov = [make_lesson(session, tid, geometry.id, date(2026, 11, d)) for d in range(1, 14)]
    # архівний клас із груднєвим уроком: загальні налаштування його не чіпають
    old = make_class(session, tid, "8-Б", "2025-2026", students=STUDENTS[3:5])
    old_journal = make_journal(session, tid, old.id, "Алгебра")
    old_dec = make_lesson(session, tid, old_journal.id, date(2025, 12, 9))
    ClassService(session).set_class_archived(tid, old.id, True)
    assert [semester_of(session, x.id) for x in (nov, dec, jan, dec_geo, old_dec)] == [1, 1, 2, 1, 1]

    journals = window.journals_page
    open_nav(window, 1)
    journals.open_journal(algebra.id)
    assert [x.id for x in journals.grid_view.grid_model.lessons] == [nov.id, dec.id]
    open_nav(window, 2)
    card = window.semesters_card
    assert card.boundaries() == DEFAULT_BOUNDARIES

    def choose(s1_end: int, s2_start: int):
        card.s1_end.setCurrentIndex(card.s1_end.findData(s1_end))
        card.s2_start.setCurrentIndex(card.s2_start.findData(s2_start))

    # --- I: вересень–листопад, II: грудень–червень ---
    choose(11, 12)
    card.save_button.click()
    assert card.status.text() == "Збережено. Оновлено журналів: 2", card.status.text()
    assert card.error.isHidden()
    assert [semester_of(session, x.id) for x in (nov, dec, jan, dec_geo)] == [1, 2, 2, 2]
    assert semester_of(session, old_dec.id) == 1, "архівний клас не чіпаємо"
    assert SettingsService(session).get_semesters(tid) == SemesterBoundaries(9, 11, 12, 6)
    assert service.get_grid(tid, algebra.id, 1).journal.boundaries == SemesterBoundaries(9, 11, 12, 6)
    assert [j.boundaries for j in service.list_journals(tid, True) if j.class_name == "8-Б"] == [DEFAULT_BOUNDARIES]
    assert [x.id for x in journals.grid_view.grid_model.lessons] == [nov.id], "відкритий журнал оновився одразу"
    journals.semester_buttons[2].click()
    assert [x.id for x in journals.grid_view.grid_model.lessons] == [dec.id, jan.id]

    # --- конфлікт: I — вересень–жовтень, листопадові уроки потрапили б у канікули ---
    choose(10, 12)
    card.save_button.click()
    assert not card.error.isHidden() and card.status.isHidden()
    text = card.error.text()
    assert text.startswith("Зміну не збережено: уроки потрапляють у канікули:\n"), text
    lines = text.splitlines()[1:]
    assert lines[0] == "9-А · Алгебра — 10.11.2026"
    assert len(lines) == 11 and lines[-1] == "і ще 4", "14 конфліктів: перші 10 і «і ще 4»"
    assert (card.s1_end.currentData(), card.s2_start.currentData()) == (11, 12), "комбо повернулись до збережених"
    assert SettingsService(session).get_semesters(tid) == SemesterBoundaries(9, 11, 12, 6)
    assert [semester_of(session, x.id) for x in (nov, dec, jan, dec_geo)] == [1, 2, 2, 2]
    assert all(semester_of(session, x.id) == 1 for x in geo_nov)

    # --- неприпустимі межі: перетин семестрів ---
    card.s1_end.setCurrentIndex(card.s1_end.findData(12))
    card.s2_start.setCurrentIndex(card.s2_start.findData(11))
    card.save_button.click()
    assert "перетинатися" in card.error.text()
    assert SettingsService(session).get_semesters(tid) == SemesterBoundaries(9, 11, 12, 6)
    assert not [m for m in msgs if m[0] == "critical"]



# ---------------------------------------------------------------------------
# S4. Архівний клас: журнал редагується, але не видаляється; межі журналу; повернення з архіву
# ---------------------------------------------------------------------------


def card_title(card) -> str:
    return card.findChildren(QLabel)[0].text()


def test_s4_archived_class_and_restore(window, teacher, session, drive, qtbot, msgs):
    tid = teacher.id
    service = JournalService(session)
    classes, journals = window.classes_page, window.journals_page
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:3])
    alg = make_journal(session, tid, c9.id, "Алгебра")
    nov = make_lesson(session, tid, alg.id, date(2026, 11, 10))
    dec = make_lesson(session, tid, alg.id, date(2026, 12, 8))
    c10 = make_class(session, tid, "10-Б", students=STUDENTS[3:5])
    phys = make_journal(session, tid, c10.id, "Фізика")

    # --- архівування з журналами: кнопка «Архівувати», підтвердження, клас зникає зі списку ---
    open_nav(window, 0)
    classes.open_class(c9.id)
    assert classes.remove_class_btn.text() == "Архівувати"
    run = drive(confirm_with("Архівувати"))
    classes.remove_class_btn.click()
    run.check()
    assert classes.stack.currentIndex() == 0
    assert sorted(card_title(c) for c in classes_cards(classes)) == ["10-Б"]
    classes.archived_check.setChecked(True)
    assert sorted(card_title(c) for c in classes_cards(classes)) == ["10-Б", "9-А"]
    classes.open_class(c9.id)
    assert not classes.restore_class_btn.isHidden()
    assert all(w.isHidden() for w in (classes.add_student_btn, classes.import_btn, classes.edit_class_btn, classes.remove_class_btn))
    assert classes.student_buttons.isHidden()
    assert classes.detail_subtitle.text().endswith("клас в архіві")
    with pytest.raises(ClassError, match="спершу поверніть"):
        ClassService(session).add_student(tid, c9.id, "Тестовий Іван")

    # --- журнал архівного класу: видно в архіві, уроки й оцінки редагуються, видалення вимкнено ---
    open_nav(window, 1)
    assert [card_title(c) for c in journal_cards(journals)] == ["10-Б · Фізика"]
    journals.archived_check.setChecked(True)
    assert sorted(card_title(c) for c in journal_cards(journals)) == ["10-Б · Фізика", "9-А · Алгебра"]
    journals.open_journal(alg.id)
    assert journals.subtitle_label.text() == f"{YEAR} · клас в архіві"
    assert not journals.delete_journal_action.isEnabled()
    assert journals.new_lesson_btn.isVisible()

    def past_lesson(dlg):
        dlg.date_edit.setDate(QDate(2026, 9, 15))
        dlg.topic_edit.setText("Пропущений урок")
        QTest.keyClick(dlg.topic_edit, ENTER)

    run = drive(past_lesson)
    journals.new_lesson_btn.click()
    run.check()
    type_text(journals.grid_view, "7")  # курсор стоїть на першій клітинці нового уроку
    grid, cells = grid_cells(session, tid, alg.id)
    new_lesson = next(x for x in grid.lessons if x.topic == "Пропущений урок")
    assert new_lesson.lesson_date == date(2026, 9, 15) and grid.lessons[0].id == new_lesson.id
    assert cells[(grid.students[0].id, new_lesson.id)].grade == 7, "оцінка в архівному журналі збережена"

    before = len(msgs)
    journals._on_delete_journal()  # пункт меню вимкнено; прямий виклик нічого не робить і не відкриває вікон
    assert len(msgs) == before
    with pytest.raises(JournalError, match="не можна видалити"):
        service.delete_journal(tid, alg.id, with_contents=True)
    assert alg.id in [j.id for j in service.list_journals(tid, True)]

    # --- «Налаштування журналу»: конфлікт нічого не змінює й повертає комбо; допустима зміна зберігається ---
    def edit_bounds(dlg):
        assert dlg.editable and all(c.isEnabled() for c in dlg.combos.values()) and dlg.note_label.isHidden()
        dlg.combos["s1_end"].setCurrentIndex(9)       # жовтень: листопад і грудень стали б канікулами
        dlg.combos["s2_start"].setCurrentIndex(0)
        button(dlg, "Зберегти").click()
        assert dlg.isVisible() and not dlg.error_label.isHidden()
        assert dlg.error_label.text().startswith("Зміну не збережено"), dlg.error_label.text()
        assert "10.11.2026" in dlg.error_label.text() and "08.12.2026" in dlg.error_label.text()
        assert [dlg.combos[k].currentData() for k in ("s1_end", "s2_start")] == [12, 1], "комбо повернулись"
        dlg.combos["s1_end"].setCurrentIndex(10)      # листопад
        dlg.combos["s2_start"].setCurrentIndex(11)    # грудень
        QTest.keyClick(dlg.combos["s2_start"], ENTER)  # Enter = «Зберегти»

    run = drive(edit_bounds)
    journals._on_journal_settings()
    run.check()
    assert not run.stayed_open
    assert service.get_grid(tid, alg.id, 1).journal.boundaries == SemesterBoundaries(9, 11, 12, 6)
    assert [semester_of(session, x.id) for x in (nov, dec)] == [1, 2]

    # --- журнал класу в роботі: межі лише для перегляду, з поясненням ---
    journals.show_list()
    journals.open_journal(phys.id)

    def inspect_active(dlg):
        assert not dlg.editable and not any(c.isEnabled() for c in dlg.combos.values())
        assert dlg.save_button.isHidden() and dlg.note_label.text() == "Змінюється в Налаштуваннях"
        QTest.keyClick(dlg, Qt.Key.Key_Escape)

    run = drive(inspect_active)
    journals._on_journal_settings()
    run.check()
    assert not run.stayed_open

    # --- повернення з архіву: межі журналів синхронізуються з Налаштуваннями, уроки перераховуються ---
    open_nav(window, 0)
    classes.open_class(c9.id)
    classes.restore_class_btn.click()
    assert not [m for m in msgs if m[0] == "warning"], msgs
    assert not classes.edit_class_btn.isHidden() and classes.restore_class_btn.isHidden()
    assert service.get_grid(tid, alg.id, 1).journal.boundaries == DEFAULT_BOUNDARIES
    assert [semester_of(session, x.id) for x in (nov, dec)] == [1, 1]
    assert classes.remove_class_btn.text() == "Архівувати"

    # --- повернення з конфліктом: клас лишається в архіві, повідомлення перелічує уроки ---
    ClassService(session).set_class_archived(tid, c9.id, True)
    SettingsService(session).set_semesters(tid, SemesterBoundaries(9, 10, 1, 6))  # листопад і грудень — канікули
    classes.open_class(c9.id)
    assert not classes.restore_class_btn.isHidden()
    classes.restore_class_btn.click()
    kind, title, text = msgs[-1]
    assert (kind, title) == ("warning", "Клас не повернуто з архіву")
    assert text.startswith("Зміну не збережено: ці уроки потрапляють у канікули.\n")
    assert "9-А · Алгебра — 10.11.2026" in text and "9-А · Алгебра — 08.12.2026" in text
    assert "«Налаштування» → «Семестри»" in text and "Налаштування журналу" not in text
    assert not classes.restore_class_btn.isHidden(), "клас лишився в архіві"
    assert [c.archived for c in ClassService(session).list_classes(tid, True) if c.id == c9.id] == [True]
    assert [semester_of(session, x.id) for x in (nov, dec)] == [1, 1]
    assert phys.id



@pytest.mark.parametrize("recovery", ["settings", "move_lesson"])
def test_s4_restore_conflict_hint_works(recovery, window, teacher, session, drive, msgs):
    """QA-B1: обидва виходи з поради (межі в Налаштуваннях / перенесення уроку) справді дозволяють повернути клас."""
    tid = teacher.id
    classes = window.classes_page
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:3])
    alg = make_journal(session, tid, c9.id, "Алгебра")
    lesson = make_lesson(session, tid, alg.id, date(2026, 11, 10))
    ClassService(session).set_class_archived(tid, c9.id, True)
    SettingsService(session).set_semesters(tid, SemesterBoundaries(9, 10, 1, 6))  # листопад — канікули

    open_nav(window, 0)
    classes.open_class(c9.id)
    classes.restore_class_btn.click()
    kind, title, text = msgs[-1]
    assert (kind, title) == ("warning", "Клас не повернуто з архіву")
    assert "«Налаштування» → «Семестри»" in text and "Налаштування журналу" not in text

    if recovery == "settings":
        # порада 1: змінити межі в «Налаштування» → «Семестри» (листопад знову в I семестрі)
        open_nav(window, 2)
        card = window.semesters_card
        for combo, month in ((card.s1_start, 9), (card.s1_end, 12), (card.s2_start, 1), (card.s2_end, 6)):
            combo.setCurrentIndex(combo.findData(month))
        card.save_button.click()
    else:
        # порада 2: перенести урок із канікул у журналі архівного класу (його можна редагувати)
        JournalService(session).update_lesson(tid, lesson.id, date(2026, 10, 12), "regular", None)

    open_nav(window, 0)
    classes.open_class(c9.id)
    classes.restore_class_btn.click()
    assert [m[1] for m in msgs].count("Клас не повернуто з архіву") == 1, msgs  # нових відмов немає
    assert [c.archived for c in ClassService(session).list_classes(tid, True) if c.id == c9.id] == [False]


# ---------------------------------------------------------------------------
# S5. Перехід на новий навчальний рік (сьогодні = 1 серпня 2027)
# ---------------------------------------------------------------------------

AUG_1 = date(2027, 8, 1)


def never_dialog(items, parent):
    raise AssertionError("вікно переходу не мало з'явитися")


def classes_of(session, teacher_id: int):
    return [(c.name, c.school_year, c.archived, c.student_count) for c in ClassService(session).list_classes(teacher_id, True)]


def test_s5_rollover_flow(window, teacher, session, drive, qtbot, msgs):
    tid = teacher.id
    service = JournalService(session)
    classes, journals = window.classes_page, window.journals_page
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:5])
    ClassService(session).set_student_archived(tid, student_ids(session, tid, c9.id)[sorted(STUDENTS[:5])[0]], True)
    alg = make_journal(session, tid, c9.id, "Алгебра")
    geo = make_journal(session, tid, c9.id, "Геометрія")
    lesson = make_lesson(session, tid, alg.id, date(2026, 10, 5), "regular", "Тема")
    service.set_cell(tid, lesson.id, student_ids(session, tid, c9.id)[sorted(STUDENTS[1:5])[0]], "present", 9, None)
    c10 = make_class(session, tid, "10-Б", students=STUDENTS[5:8])
    make_journal(session, tid, c10.id, "Фізика")
    c11 = make_class(session, tid, "11-Б", students=STUDENTS[8:10])
    make_journal(session, tid, c11.id, "Математика")
    assert geo.id

    # сторінки відкриті на «старих» даних: клас 9-А (деталі) і журнал 9-А · Алгебра
    open_nav(window, 0)
    classes.open_class(c9.id)
    open_nav(window, 1)
    journals.open_journal(alg.id)
    assert journals.stack.currentIndex() == 1

    # --- до 1 серпня пропонувати нічого ---
    assert maybe_run_rollover(window, tid, date(2027, 7, 31), dialog_factory=never_dialog) is False

    # --- «Пізніше»: нічого не змінюється ---
    snapshot = classes_of(session, tid)

    def later(dlg):
        assert [line.text() for line in dlg.lines] == [
            "9-А → 10-А (2027-2028), учнів: 4",
            "10-Б → 11-Б (2027-2028), учнів: 3",
            "11-Б → 12-Б (2027-2028), учнів: 2",  # останній клас — 12-й (рішення викладачки)
        ]
        assert not dlg.copy_check.isHidden() and not dlg.copy_check.isChecked(), "галочка за замовчуванням вимкнена"
        assert dlg.ok_button.isDefault()
        dlg.later_button.click()

    run = drive(later)
    assert maybe_run_rollover(window, tid, AUG_1) is False
    run.check()
    assert classes_of(session, tid) == snapshot
    assert journals.stack.currentIndex() == 1 and classes.stack.currentIndex() == 1, "сторінки не змінились"

    # --- «Гаразд» з галочкою: нові класи, учні, журнали; обидві сторінки оновлюються ---
    def agree(dlg):
        dlg.copy_check.setChecked(True)
        assert dlg.copy_journals
        dlg.ok_button.click()

    run = drive(agree)
    assert maybe_run_rollover(window, tid, AUG_1) is True
    run.check()
    rows = classes_of(session, tid)
    assert sorted(rows) == sorted([
        ("9-А", YEAR, True, 4), ("10-Б", YEAR, True, 3), ("11-Б", YEAR, True, 2),
        ("10-А", "2027-2028", False, 4), ("11-Б", "2027-2028", False, 3), ("12-Б", "2027-2028", False, 2),
    ])
    new_10a = next(c for c in ClassService(session).list_classes(tid) if c.name == "10-А")
    new_students = ClassService(session).list_students(tid, new_10a.id)
    assert [s.position for s in new_students] == [1, 2, 3, 4] and not any(s.archived for s in new_students)
    old_students = {s.id for s in ClassService(session).list_students(tid, c9.id)}
    assert not old_students & {s.id for s in new_students}, "учні нового класу — нові записи"
    by_class = {}
    for j in service.list_journals(tid):
        by_class.setdefault(j.class_name, []).append((j.subject_name, j.lesson_count, j.boundaries))
    assert by_class == {
        "10-А": [("Алгебра", 0, DEFAULT_BOUNDARIES), ("Геометрія", 0, DEFAULT_BOUNDARIES)],
        "11-Б": [("Фізика", 0, DEFAULT_BOUNDARIES)],
        "12-Б": [("Математика", 0, DEFAULT_BOUNDARIES)],  # 11-Б → 12-Б (етап 6)
    }, "журнали скопійовано порожніми"
    old = service.get_grid(tid, alg.id, 1)
    assert old.journal.class_archived and len(old.lessons) == 1 and len(old.cells) == 1, "старий журнал без змін"

    # сторінки оновились: «Класи» — список нових класів, «Журнали» — відкритий журнал уже з позначкою архіву
    assert classes.stack.currentIndex() == 0
    assert sorted(card_title(c) for c in classes_cards(classes)) == ["10-А", "11-Б", "12-Б"]
    assert journals.stack.currentIndex() == 1
    assert journals.subtitle_label.text() == f"{YEAR} · клас в архіві"
    journals.show_list()
    assert sorted(card_title(c) for c in journal_cards(journals)) == [
        "10-А · Алгебра", "10-А · Геометрія", "11-Б · Фізика", "12-Б · Математика",
    ]

    # --- повторний запуск: пропонувати нічого, вікна немає ---
    assert maybe_run_rollover(window, tid, AUG_1, dialog_factory=never_dialog) is False
    assert not [m for m in msgs if m[0] in ("warning", "critical")]

    # --- крайні випадки: 11-Б, «Гурток», існуюча ціль, 20-символьна назва, «09-А» поруч із «9-А» ---
    rollover_edge_classes(window, session, drive, msgs)


def rollover_edge_classes(window, session, drive, msgs):
    """Крайні випадки переходу на новий рік — для другого викладача (щоб назви не збігалися з основним сценарієм)."""
    second = Teacher(username="second_teacher", password_hash="x", full_name="Другий Викладач")
    session.add(second)
    session.flush()
    tid = second.id
    long_name = "9-" + "Ф" * 18
    assert len(long_name) == 20
    c_a = make_class(session, tid, "9-А", students=STUDENTS[:3])
    c_a0 = make_class(session, tid, "09-А", students=STUDENTS[3:5])
    c_b = make_class(session, tid, "9-Б", students=STUDENTS[5:8])
    existing = make_class(session, tid, "10-Б", "2027-2028", students=STUDENTS[8:10])
    make_class(session, tid, "11-Б", students=STUDENTS[10:12])
    make_class(session, tid, "Гурток", students=STUDENTS[12:14])
    make_class(session, tid, long_name, students=STUDENTS[14:16])
    assert c_a.id and c_a0.id and c_b.id

    def agree_with_enter(dlg):
        texts = sorted(line.text() for line in dlg.lines)
        assert "9-Б → архів (10-Б уже існує)" in texts
        assert "11-Б → 12-Б (2027-2028), учнів: 2" in texts and "Гурток → архів" in texts and f"{long_name} → архів" in texts
        promoted = [t for t in texts if "→ 10-А (2027-2028)" in t]
        duplicated = [t for t in texts if t.endswith("→ архів (10-А уже існує)")]
        assert len(promoted) == 1 and len(duplicated) == 1, texts
        assert dlg.copy_check.isHidden() and not dlg.copy_journals, "немає журналів — галочки немає"
        QTest.keyClick(dlg, ENTER)  # Enter = «Гаразд»

    run = drive(agree_with_enter)
    assert maybe_run_rollover(window, tid, AUG_1) is True
    run.check()
    assert not run.stayed_open
    rows = classes_of(session, tid)
    names_2026 = {(n, a) for n, y, a, _ in rows if y == YEAR}
    assert names_2026 == {("9-А", True), ("09-А", True), ("9-Б", True), ("11-Б", True), ("Гурток", True), (long_name, True)}
    new_rows = [(n, a) for n, y, a, _ in rows if y == "2027-2028"]
    assert sorted(new_rows) == [("10-А", False), ("10-Б", False), ("12-Б", False)], "жодних зайвих класів (10-Гурток…) не створено"
    assert [c for c in rows if c[0] == "10-Б" and c[1] == "2027-2028"][0][3] == 2, "існуючий 10-Б не чіпали"
    assert existing.id
    assert maybe_run_rollover(window, tid, AUG_1, dialog_factory=never_dialog) is False

    # --- без журналів і без promote: галочки немає, вікно показує лише архівування ---
    c_only = make_class(session, tid, "Гурток-2", "2026-2027")
    assert c_only.id

    def only_archive(dlg):
        assert [line.text() for line in dlg.lines] == ["Гурток-2 → архів"]
        assert dlg.copy_check.isHidden()
        dlg.ok_button.click()

    run = drive(only_archive)
    assert maybe_run_rollover(window, tid, AUG_1) is True
    run.check()
    assert not [m for m in msgs if m[0] in ("warning", "critical")]



# ---------------------------------------------------------------------------
# S6. Видалення журналу словом; клас із журналами — лише в архів
# ---------------------------------------------------------------------------


def test_s6_delete_journal_and_class(window, teacher, session, drive, msgs):
    tid = teacher.id
    service, class_service = JournalService(session), ClassService(session)
    classes, journals = window.classes_page, window.journals_page
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:3])
    alg = make_journal(session, tid, c9.id, "Алгебра")
    geo = make_journal(session, tid, c9.id, "Геометрія")
    lessons = [make_lesson(session, tid, alg.id, date(2026, 11, d)) for d in (3, 10)]
    ids = student_ids(session, tid, c9.id)
    service.set_cell(tid, lessons[0].id, ids[sorted(ids)[0]], "present", 8, "Коментар")
    service.set_cell(tid, lessons[1].id, ids[sorted(ids)[1]], "absent", None, None)
    c10 = make_class(session, tid, "10-Б", students=STUDENTS[3:6])
    c8 = make_class(session, tid, "8-В", students=STUDENTS[6:8])
    phys = make_journal(session, tid, c8.id, "Фізика")
    make_lesson(session, tid, phys.id, date(2026, 10, 1))

    # --- журнал з уроками: Esc нічого не робить; слово «видалити» видаляє журнал із вмістом ---
    open_nav(window, 1)
    journals.open_journal(alg.id)
    run = drive(lambda dlg: QTest.keyClick(dlg, Qt.Key.Key_Escape))
    journals._on_delete_journal()
    run.check()
    assert alg.id in [j.id for j in service.list_journals(tid)]

    run = drive(typed_confirm("видалити"))
    journals.delete_journal_action.trigger()
    run.check()
    assert isinstance(run.seen, DeleteJournalDialog) and "містить уроків: 2" in run.seen.findChildren(QLabel)[1].text()
    assert journals.stack.currentIndex() == 0
    assert [j.subject_name for j in service.list_journals(tid) if j.class_name == "9-А"] == ["Геометрія"]
    assert session.scalar(select(func.count()).select_from(Lesson).where(Lesson.journal_id == alg.id)) == 0
    assert session.scalar(
        select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id.in_([x.id for x in lessons]))
    ) == 0
    assert len(ClassService(session).list_students(tid, c9.id)) == 3, "учні лишились"
    assert [c.archived for c in class_service.list_classes(tid)].count(False) == 3

    # --- порожній журнал: звичайне підтвердження, за замовчуванням «Скасувати» ---
    journals.open_journal(geo.id)
    seen: list[str] = []
    run = drive(confirm_with("Скасувати", seen))
    journals._on_delete_journal()
    run.check()
    assert geo.id in [j.id for j in service.list_journals(tid)]
    assert seen == ["Видалити журнал «9-А · Геометрія»? Цю дію не можна скасувати."]
    run = drive(confirm_with("Видалити"))
    journals._on_delete_journal()
    run.check()
    assert geo.id not in [j.id for j in service.list_journals(tid)] and journals.stack.currentIndex() == 0

    # --- клас із журналами: лише архів (і в БД, і в інтерфейсі) ---
    open_nav(window, 0)
    classes.open_class(c8.id)
    assert classes.remove_class_btn.text() == "Архівувати"
    with pytest.raises(ClassError, match="лише перенести в архів"):
        class_service.delete_class(tid, c8.id)
    seen = []
    run = drive(confirm_with("Архівувати", seen))
    classes.remove_class_btn.click()
    run.check()
    assert "Журнали та оцінки збережуться" in seen[0]
    assert [(c.name, c.archived) for c in class_service.list_classes(tid, True) if c.id == c8.id] == [("8-В", True)]
    assert phys.id in [j.id for j in service.list_journals(tid, True)]

    # --- клас без журналів: видалення разом зі списком учнів ---
    classes.open_class(c10.id)
    assert classes.remove_class_btn.text() == "Видалити клас"
    seen = []
    run = drive(confirm_with("Видалити", seen))
    classes.remove_class_btn.click()
    run.check()
    assert seen == ["Видалити клас «10-Б» разом зі списком учнів (3)? Цю дію не можна скасувати."]
    assert c10.id not in [c.id for c in class_service.list_classes(tid, True)]
    assert session.scalar(select(func.count()).select_from(Student).where(Student.class_id == c10.id)) == 0

    # --- 9-А тепер без журналів: теж можна видалити, а не архівувати ---
    classes.open_class(c9.id)
    assert classes.remove_class_btn.text() == "Видалити клас"
    assert not [m for m in msgs if m[0] in ("warning", "critical")]


# ---------------------------------------------------------------------------
# S7. Перемикання теми при відкритому журналі
# ---------------------------------------------------------------------------


def pixel(widget, point: QPoint) -> str:
    return widget.grab().toImage().pixelColor(point).name().upper()


def test_s7_theme_switch(window, teacher, session, qtbot, msgs):
    tid = teacher.id
    service = JournalService(session)
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:5])
    alg = make_journal(session, tid, c9.id, "Алгебра")
    kinds = ["regular", "test", "lab", "independent"]
    lessons = [make_lesson(session, tid, alg.id, date(2026, 11, 2 + i), kind) for i, kind in enumerate(kinds)]
    ids = student_ids(session, tid, c9.id)
    ordered = [ids[n] for n in sorted(ids, key=lambda n: n)]
    leaver = ordered[4]
    service.set_cell(tid, lessons[0].id, ordered[1], "absent", None, None)
    service.set_cell(tid, lessons[0].id, ordered[2], "present", 9, "Є коментар")
    service.set_cell(tid, lessons[0].id, leaver, "present", 6, None)
    ClassService(session).set_student_archived(tid, leaver, True)

    open_nav(window, 1)
    journals = window.journals_page
    journals.open_journal(alg.id)
    window.classes_page.open_class(c9.id)
    view, panel = journals.grid_view, journals.lesson_panel
    view.select_cell(0, 3)  # виділена клітинка не в зонах перевірки
    qtbot.wait(50)

    def snapshot():
        model = view.grid_model
        empty = view.visualRect(model.index(2, 2)).center()                # порожня клітинка
        absent = view.visualRect(model.index(model.students.index(next(s for s in model.students if s.id == ordered[1])), 0)).center()
        header_test = QPoint(view.horizontalHeader().sectionViewportPosition(1) + 4, 4)  # куточок заголовка КР
        return {
            "cell": pixel(view.viewport(), empty),
            "absent": pixel(view.viewport(), absent),
            "header": pixel(view.horizontalHeader().viewport(), header_test),
            "panel_row": panel.table.item(1, 2).background().color().name().upper(),
            "muted_student": window.classes_page.table.item(len(window.classes_page._students) - 1, 1).foreground().color().name().upper(),
        }

    def expected(name: str):
        t = theme.TOKENS[name]
        return {
            "cell": t["surface"], "absent": t["mark_absent_soft"], "header": t["lesson_test_soft"],
            "panel_row": t["lesson_test_soft"], "muted_student": t["muted"],
        }

    def norm(d):
        return {k: v.upper() for k, v in d.items()}

    assert snapshot() == norm(expected("light"))
    dark_button = next(b for b in window.theme_group.buttons() if b.property("themeName") == "dark")
    dark_button.click()
    qtbot.wait(50)
    assert theme.current_theme() == "dark"
    assert snapshot() == norm(expected("dark")), "таблиця, шапка, панель уроків і «Класи» перемальовано в темній темі"
    assert QApplication.instance().styleSheet().count(theme.TOKENS["dark"]["bg"]) >= 1

    # у темній темі працюють сторінки й діалоги без помилок
    journals.semester_buttons[2].click()
    journals.semester_buttons[1].click()
    open_nav(window, 2)
    open_nav(window, 1)
    light_button = next(b for b in window.theme_group.buttons() if b.property("themeName") == "light")
    light_button.click()
    qtbot.wait(50)
    assert snapshot() == norm(expected("light")), "повернення до світлої теми"
    assert not [m for m in msgs if m[0] in ("warning", "critical")]



# ---------------------------------------------------------------------------
# S8. Лише клавіатура: порядок Tab, Enter = кнопка за замовчуванням, Esc, «Скасувати» у підтвердженнях
# ---------------------------------------------------------------------------


def describe(widget) -> str:
    """Короткий опис елемента фокуса (поле з внутрішнім QLineEdit лічильника дати — як одна «дата»)."""
    while widget is not None and isinstance(widget.parent(), QAbstractSpinBox):
        widget = widget.parent()
    if isinstance(widget, QPushButton):
        return f"кнопка «{widget.text()}»"
    if isinstance(widget, QAbstractSpinBox):
        return "дата"
    if isinstance(widget, QLineEdit):
        return f"поле «{widget.placeholderText()}»"
    if isinstance(widget, QComboBox):
        return "список"
    if isinstance(widget, QCheckBox):
        return f"галочка «{widget.text()}»"
    if isinstance(widget, QPlainTextEdit):
        return "текст"
    return type(widget).__name__


def show_dialog(dlg, qtbot):
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is dlg)
    return dlg


def focus_chain(dlg, limit: int = 12) -> list[str]:
    """Описи елементів у порядку, в якому їх обходить клавіша Tab (починаючи з початкового фокуса)."""
    first = dlg.focusWidget()
    widgets, chain = [first], [describe(first)]
    for _ in range(limit):
        QTest.keyClick(dlg, Qt.Key.Key_Tab)
        current = dlg.focusWidget()
        if current is first or current is widgets[-1]:
            break
        widgets.append(current)
        chain.append(describe(current))
    return chain


def test_s8_keyboard_only_dialogs(window, teacher, session, drive, qtbot, msgs):
    tid = teacher.id
    service, class_service = JournalService(session), ClassService(session)
    classes, journals = window.classes_page, window.journals_page
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:3])
    alg = make_journal(session, tid, c9.id, "Алгебра")
    lesson = make_lesson(session, tid, alg.id, date(2026, 11, 3))
    ids = student_ids(session, tid, c9.id)
    service.set_cell(tid, lesson.id, ids[sorted(ids)[0]], "present", 8, None)
    old = make_class(session, tid, "8-Б", "2025-2026", students=STUDENTS[3:5])
    old_journal = make_journal(session, tid, old.id, "Фізика")
    class_service.set_class_archived(tid, old.id, True)
    factory = default_api_factory

    def rejected_by_escape(make):
        dlg = show_dialog(make(), qtbot)
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.result() == 0 and not dlg.isVisible(), f"Esc не закрив {type(dlg).__name__}"

    def accepted_by_enter(make, prepare, widget_name=None):
        dlg = show_dialog(make(), qtbot)
        target = prepare(dlg)
        QTest.keyClick(target, ENTER)
        assert dlg.result() == 1 and not dlg.isVisible(), f"Enter не підтвердив {type(dlg).__name__}"
        return dlg

    # --- Esc у кожному діалозі ---
    items = RolloverService(session).plan(tid, AUG_1)
    assert items
    journal_info = next(j for j in service.list_journals(tid, True) if j.id == old_journal.id)
    for make in (
        lambda: ClassDialog(tid),
        lambda: StudentDialog(tid, c9.id),
        lambda: ImportStudentsDialog(tid, c9.id),
        lambda: LessonDialog(tid, factory, alg.id),
        lambda: NewJournalDialog(tid, factory),
        lambda: JournalSettingsDialog(tid, factory, journal_info),
        lambda: CommentDialog("текст"),
        lambda: DeleteJournalDialog(journal_info, 3),
        lambda: RolloverDialog(items),
    ):
        rejected_by_escape(make)
    assert [c.name for c in class_service.list_classes(tid)] == ["9-А"], "Esc нічого не створив"

    # --- порядок Tab збігається з візуальним ---
    chains = {
        "ClassDialog": (ClassDialog(tid), ["поле «напр. 9-А»", "список", "кнопка «Створити»"]),
        "StudentDialog": (StudentDialog(tid, c9.id), ["поле «Коваленко Олена»", "кнопка «Додати ще»", "кнопка «Додати»"]),
        "LessonDialog": (
            LessonDialog(tid, factory, alg.id),
            ["дата", "список", "поле «необов'язково»", "текст", "кнопка «Створити»"],  # + д/з (етап 6)
        ),
        "NewJournalDialog": (NewJournalDialog(tid, factory), ["список", "список", "кнопка «Створити»"]),
        "JournalSettingsDialog": (
            JournalSettingsDialog(tid, factory, journal_info),
            ["список"] * 4 + ["кнопка «Зберегти»"],
        ),
        "RolloverDialog": (
            RolloverDialog(items),
            ["галочка «Створити такі самі журнали для нових класів»", "кнопка «Пізніше»", "кнопка «Гаразд»"],
        ),
    }
    for name, (dlg, expected) in chains.items():
        assert focus_chain(show_dialog(dlg, qtbot)) == expected, name

    # --- Enter = кнопка за замовчуванням ---
    def fill_class(dlg):
        dlg.name_edit.setText("7-А")
        dlg.name_edit.setFocus()
        return dlg.name_edit

    accepted_by_enter(lambda: ClassDialog(tid), fill_class)
    assert "7-А" in [c.name for c in class_service.list_classes(tid)]

    def fill_student(dlg):
        dlg.name_edit.setText(STUDENTS[10])
        return dlg.name_edit

    accepted_by_enter(lambda: StudentDialog(tid, c9.id), fill_student)
    assert STUDENTS[10] in student_ids(session, tid, c9.id)

    def fill_lesson(dlg):
        dlg.topic_edit.setText("Урок з Enter")
        dlg.topic_edit.setFocus()
        return dlg.topic_edit

    accepted_by_enter(lambda: LessonDialog(tid, factory, alg.id), fill_lesson)
    assert "Урок з Enter" in [x.topic for x in service.get_grid(tid, alg.id, 1).lessons]

    def pick_subject(dlg):
        dlg.class_combo.setCurrentIndex(dlg.class_combo.findText(f"9-А · {YEAR}"))
        dlg.subject_combo.setCurrentIndex(dlg.subject_combo.findText("Фізика"))
        dlg.subject_combo.setFocus()
        return dlg.subject_combo

    accepted_by_enter(lambda: NewJournalDialog(tid, factory), pick_subject)
    assert "Фізика" in [j.subject_name for j in service.list_journals(tid) if j.class_name == "9-А"]

    def change_bounds(dlg):
        dlg.combos["s1_end"].setCurrentIndex(10)
        dlg.combos["s2_start"].setCurrentIndex(11)
        dlg.combos["s2_start"].setFocus()
        return dlg.combos["s2_start"]

    accepted_by_enter(lambda: JournalSettingsDialog(tid, factory, journal_info), change_bounds)
    assert service.get_grid(tid, old_journal.id, 1).journal.boundaries == SemesterBoundaries(9, 11, 12, 6)
    accepted_by_enter(lambda: RolloverDialog(items), lambda dlg: dlg)

    # коментар: Enter у багаторядковому полі — новий рядок, а не підтвердження
    dlg = show_dialog(CommentDialog("рядок"), qtbot)
    dlg.edit.moveCursor(dlg.edit.textCursor().MoveOperation.End)
    QTest.keyClick(dlg.edit, ENTER)
    assert dlg.isVisible() and dlg.edit.toPlainText() == "рядок\n"
    dlg.close()

    # --- діалоги з введенням слова: за замовчуванням «Скасувати» — Enter навіть після слова нічого не видаляє ---
    dlg = show_dialog(DeleteJournalDialog(journal_info, 3), qtbot)
    dlg.confirm_edit.setText("видалити")
    assert dlg.delete_button.isEnabled()
    QTest.keyClick(dlg.confirm_edit, ENTER)
    assert dlg.result() == 0 and not dlg.isVisible(), "Enter у діалозі видалення має скасовувати"

    # --- підтвердження QMessageBox: «Скасувати» за замовчуванням, Enter і Esc → False ---
    for page in (classes, journals):
        for key in (ENTER, Qt.Key.Key_Escape):
            run = drive(lambda box, key=key: QTest.keyClick(box, key))
            assert page._confirm("Видалити все?", "Видалити") is False
            run.check()
            assert not run.stayed_open
    assert [c.name for c in class_service.list_classes(tid)].count("9-А") == 1


# ---------------------------------------------------------------------------
# QA-B2, QA-B3 (виправлено): Tab у багаторядкових полях і граматика повідомлення про імпорт
# ---------------------------------------------------------------------------


def test_s8_tab_leaves_multiline_fields(window, teacher, session, qtbot):
    tid = teacher.id
    c9 = make_class(session, tid, "9-А")

    # після вставлення списку Tab веде до кнопки «Додати учнів»
    dlg = show_dialog(ImportStudentsDialog(tid, c9.id), qtbot)
    dlg.text_edit.setPlainText("\n".join(STUDENTS[:3]))
    dlg.update_preview()
    dlg.text_edit.setFocus()
    QTest.keyClick(dlg.text_edit, Qt.Key.Key_Tab)  # клавіша йде до елемента, що має фокус
    assert dlg.focusWidget() is dlg.submit_button, describe(dlg.focusWidget())
    assert "\t" not in dlg.text_edit.toPlainText()
    dlg.close()

    dlg = show_dialog(CommentDialog("текст"), qtbot)
    dlg.edit.setFocus()
    QTest.keyClick(dlg.edit, Qt.Key.Key_Tab)
    assert dlg.focusWidget() is not dlg.edit
    assert "\t" not in dlg.edit.toPlainText()
    dlg.close()


def test_s1_import_message_grammar(window, teacher, session, drive, msgs):
    tid = teacher.id
    c9 = make_class(session, tid, "9-А")

    def do_import(dialog):
        dialog.text_edit.setPlainText("\n".join(STUDENTS[:3]))
        dialog.update_preview()
        dialog.submit_button.click()

    run = drive(do_import)
    ImportStudentsDialog(tid, c9.id).exec()
    run.check()
    text = next(m[2] for m in msgs if m[1] == "Імпорт завершено")
    assert text.startswith("Додано 3 учні.")


# ---------------------------------------------------------------------------
# S9. Чужі ідентифікатори → «не знайдено», нічого не змінюється й не розкривається
# ---------------------------------------------------------------------------


def test_s9_foreign_ids(window, teacher, session, msgs):
    tid = teacher.id
    other = Teacher(username="other_teacher", password_hash="x", full_name="Інша Викладачка")
    session.add(other)
    session.flush()
    oid = other.id
    cs, js = ClassService(session), JournalService(session)
    classes, journals = window.classes_page, window.journals_page

    mine = make_class(session, tid, "9-А", students=STUDENTS[:3])
    my_journal = make_journal(session, tid, mine.id, "Алгебра")
    my_lesson = make_lesson(session, tid, my_journal.id, date(2026, 11, 3))
    foreign = make_class(session, oid, "8-А", students=STUDENTS[20:23])
    foreign_journal = make_journal(session, oid, foreign.id, "Фізика")
    foreign_lesson = make_lesson(session, oid, foreign_journal.id, date(2026, 10, 6))
    foreign_student = next(iter(student_ids(session, oid, foreign.id).values()))
    foreign_snapshot = (classes_of(session, oid), student_ids(session, oid, foreign.id), js.get_grid(oid, foreign_journal.id, 1))
    missing = 999_000_000
    algebra = subject_id(session, "Алгебра")

    def message(call) -> tuple[type, str]:
        with pytest.raises((ClassError, JournalError)) as caught:
            call()
        return type(caught.value), str(caught.value)

    d = date(2026, 11, 4)
    cases = {  # назва → (викликає з id чужого/неіснуючого, очікуваний текст)
        "клас": (
            "Клас не знайдено",
            [
                lambda i: cs.list_students(tid, i),
                lambda i: cs.add_student(tid, i, "Хтось Новий"),
                lambda i: cs.import_students(tid, i, "Хтось Новий"),
                lambda i: cs.preview_import(tid, i, "Хтось Новий"),
                lambda i: cs.update_class(tid, i, "Х-Х", YEAR),
                lambda i: cs.set_class_archived(tid, i, True),
                lambda i: cs.class_removal_mode(tid, i),
                lambda i: cs.delete_class(tid, i),
                lambda i: js.create_journal(tid, i, algebra),
            ],
            (foreign.id, missing),
        ),
        "учень": (
            "Учня не знайдено",
            [
                lambda i: cs.rename_student(tid, i, "Нове Ім'я"),
                lambda i: cs.student_removal_mode(tid, i),
                lambda i: cs.delete_student(tid, i),
                lambda i: cs.set_student_archived(tid, i, True),
                lambda i: js.set_cell(tid, my_lesson.id, i, "present", 5, None),
            ],
            (foreign_student, missing),
        ),
        "журнал": (
            "Журнал не знайдено",
            [
                lambda i: js.get_grid(tid, i, 1),
                lambda i: js.create_lesson(tid, i, d, "regular", None),
                lambda i: js.set_journal_semesters(tid, i, DEFAULT_BOUNDARIES),
                lambda i: js.delete_journal(tid, i, with_contents=True),
            ],
            (foreign_journal.id, missing),
        ),
        "урок": (
            "Урок не знайдено",
            [
                lambda i: js.update_lesson(tid, i, d, "regular", "Хак"),
                lambda i: js.delete_lesson(tid, i),
                lambda i: js.set_cell(tid, i, foreign_student, "present", 5, None),
            ],
            (foreign_lesson.id, missing),
        ),
    }
    for kind, (expected, calls, (foreign_id, missing_id)) in cases.items():
        for call in calls:
            f_type, f_text = message(lambda: call(foreign_id))
            m_type, m_text = message(lambda: call(missing_id))
            assert f_text == m_text == expected, f"{kind}: чужий «{f_text}», неіснуючий «{m_text}»"
            assert f_type is m_type

    # власні дані й дані іншого викладача не змінились; у списках чужого немає
    assert (classes_of(session, oid), student_ids(session, oid, foreign.id), js.get_grid(oid, foreign_journal.id, 1)) == foreign_snapshot
    assert [c.name for c in cs.list_classes(tid, True)] == ["9-А"]
    assert [j.id for j in js.list_journals(tid, True)] == [my_journal.id]
    assert {c.class_id for c in js.list_journal_candidates(tid)} == {mine.id}
    assert [i.class_name for i in RolloverService(session).plan(tid, AUG_1)] == ["9-А"]
    RolloverService(session).apply(tid, AUG_1)
    assert classes_of(session, oid) == foreign_snapshot[0], "перехід на новий рік не чіпає чужі класи"

    # інтерфейс: чужий клас → повідомлення «Клас не знайдено» і повернення до списку; чужий журнал → до списку
    open_nav(window, 0)
    classes.open_class(foreign.id)
    assert msgs[-1] == ("warning", "Не вдалося виконати дію", "Клас не знайдено")
    assert classes.stack.currentIndex() == 0
    open_nav(window, 1)
    count = len(msgs)
    journals.open_journal(foreign_journal.id)
    assert journals.stack.currentIndex() == 0 and journals._journal_id is None
    assert len(msgs) == count, "чужий журнал: без вікон і винятків"


# ---------------------------------------------------------------------------
# S10. Журнал помилок не містить імен учнів (навіть коли БД повертає рядок із даними)
# ---------------------------------------------------------------------------


def test_s10_log_has_no_student_names(window, teacher, session, log_file, monkeypatch, msgs):
    import logging

    from sqlalchemy import text

    tid = teacher.id
    c9 = make_class(session, tid, "9-А", students=STUDENTS[:5])
    logging.getLogger("qa").info("S10: початок перевірки журналу помилок")

    # Справжня помилка PostgreSQL: NOT NULL у рядку учня — повідомлення містить «DETAIL: Failing row contains (…ім'я…)».
    def failing(self, teacher_id, class_id):
        self.repo.session.execute(
            text("INSERT INTO students (class_id, full_name, position) VALUES (NULL, :name, 0)"),
            {"name": STUDENTS[0]},
        )

    with monkeypatch.context() as patch:
        patch.setattr(ClassService, "list_students", failing)
        window.classes_page.open_class(c9.id)
    assert msgs[-1][:2] == ("warning", "Помилка"), msgs[-1]
    assert STUDENTS[0] not in msgs[-1][2], "повідомлення користувачу теж без імені"

    for handler in logging.getLogger().handlers:
        handler.flush()
    log = log_file.read_text(encoding="utf-8")
    assert "Помилка під час роботи з класами" in log and "S10: початок" in log, "помилку записано в журнал"
    assert "DETAIL: [приховано]" in log or "Failing row" not in log
    leaked = sorted(name for name in ALL_STUDENT_NAMES if name in log)
    assert not leaked, f"імена учнів у журналі помилок: {leaked}"
    for surname in SURNAMES:
        assert surname not in log, f"прізвище «{surname}» у журналі"
    assert "Демо Викладач" not in log and "demo_teacher" not in log and "other_teacher" not in log
    assert "password_hash" not in log.lower() or "[SQL:" not in log


# @@END@@

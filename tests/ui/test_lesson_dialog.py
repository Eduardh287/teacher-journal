"""Діалог уроку (етап 6): шість типів із датою та поле «Домашнє завдання» (без БД, з простим стабом сервісу)."""
from contextlib import contextmanager
from datetime import date

import pytest
from PySide6.QtWidgets import QLabel

from journal.services.journal_types import MAX_HOMEWORK, JournalError, LessonInfo
from journal.ui.journal_dialogs import EXTRA_COLUMN_TYPES, FINAL_COLUMN_TITLES, LESSON_TYPES, LessonDialog


class StubApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    def create_lesson(self, teacher_id, journal_id, lesson_date, lesson_type="regular", topic=None, homework=None):
        if self.error:
            raise self.error
        self.calls.append(("create", journal_id, lesson_date, lesson_type, topic, homework))
        return LessonInfo(1, lesson_date, 1, lesson_type, topic, 0, homework, 1)

    def update_lesson(self, teacher_id, lesson_id, lesson_date, lesson_type, topic, homework=None):
        self.calls.append(("update", lesson_id, lesson_date, lesson_type, topic, homework))
        return LessonInfo(lesson_id, lesson_date, 1, lesson_type, topic, 0, homework, 1)


@pytest.fixture
def api():
    return StubApi()


@pytest.fixture
def factory(api):
    @contextmanager
    def make():
        yield api

    return make


def test_six_dated_types_in_order(qtbot, factory):
    dialog = LessonDialog(1, factory, 5)
    qtbot.addWidget(dialog)
    names = [dialog.type_combo.itemText(i) for i in range(dialog.type_combo.count())]
    assert names == [
        "Звичайний урок", "Контрольна робота", "Лабораторна робота", "Самостійна робота", "Тест", "Проєкт",
    ]
    assert [dialog.type_combo.itemData(i) for i in range(6)] == list(LESSON_TYPES)
    assert LESSON_TYPES["quiz"][1] == "Т" and LESSON_TYPES["project"][1] == "Пр"


def test_dateless_constants_for_grid():
    assert EXTRA_COLUMN_TYPES == {"thematic": ("Тематична", "Тем"), "notebook": ("Зошит", "Зош")}
    assert FINAL_COLUMN_TITLES == {"semester": ("Семестрова", "Сем."), "annual": ("Річна", "Річна")}
    # дату для стовпчиків без дати задати неможливо: їх немає серед типів уроку
    assert not set(EXTRA_COLUMN_TYPES) & set(LESSON_TYPES)


def test_homework_field_present_with_label_and_limit(qtbot, factory):
    dialog = LessonDialog(1, factory, 5)
    qtbot.addWidget(dialog)
    assert "ДОМАШНЄ ЗАВДАННЯ" in [w.text() for w in dialog.findChildren(QLabel)]
    dialog.homework_edit.setPlainText("я" * (MAX_HOMEWORK + 40))
    assert len(dialog.homework_edit.toPlainText()) == MAX_HOMEWORK


def test_create_passes_homework_and_new_type(qtbot, factory, api):
    dialog = LessonDialog(1, factory, 5)
    qtbot.addWidget(dialog)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("quiz"))
    dialog.topic_edit.setText("Дроби")
    dialog.homework_edit.setPlainText("  § 5, № 12  ")
    dialog._on_submit()
    assert dialog.result_info is not None
    kind, journal_id, _d, lesson_type, topic, homework = api.calls[0]
    assert (kind, journal_id, lesson_type, topic, homework) == ("create", 5, "quiz", "Дроби", "§ 5, № 12")


def test_edit_prefills_homework_and_updates(qtbot, factory, api):
    existing = LessonInfo(7, date(2026, 10, 5), 1, "project", "Енергія", 2, "Підготувати доповідь", 4)
    dialog = LessonDialog(1, factory, 5, existing)
    qtbot.addWidget(dialog)
    assert dialog.type_combo.currentData() == "project"
    assert dialog.homework_edit.toPlainText() == "Підготувати доповідь"
    dialog.homework_edit.setPlainText("")
    dialog._on_submit()
    assert api.calls[0] == ("update", 7, date(2026, 10, 5), "project", "Енергія", "")


def test_service_error_is_shown_and_dialog_stays(qtbot, factory, api):
    api.error = JournalError("Дата припадає на канікули")
    dialog = LessonDialog(1, factory, 5)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_submit()
    assert dialog.result_info is None
    assert dialog.error_label.isVisible() and "канікули" in dialog.error_label.text()

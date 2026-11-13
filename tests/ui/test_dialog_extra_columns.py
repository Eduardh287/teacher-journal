"""«Тематична»/«Зошит» створюються в діалозі «Новий урок» (без БД, зі стабом сервісу)."""
from datetime import date

import pytest

from journal.services.journal_types import JournalError, LessonInfo
from journal.ui.journal_dialogs import LessonDialog
from tests.ui.test_lesson_dialog import StubApi, api, factory  # noqa: F401  (фікстури)


def items(dialog):
    combo = dialog.type_combo
    return [combo.itemText(i) for i in range(combo.count())]


def test_create_mode_lists_dated_types_separator_then_dateless(qtbot, factory):
    dialog = LessonDialog(1, factory, 5)
    qtbot.addWidget(dialog)
    combo = dialog.type_combo
    assert combo.count() == 9
    assert items(dialog)[6] == ""  # розділювач
    assert [combo.itemData(i) for i in (7, 8)] == ["thematic", "notebook"]
    assert [combo.itemText(i) for i in (7, 8)] == ["Тематична", "Зошит"]


def test_edit_mode_has_no_dateless_types(qtbot, factory):
    existing = LessonInfo(7, date(2026, 10, 5), 1, "regular", None, 0, None, 4)
    dialog = LessonDialog(1, factory, 5, existing)
    qtbot.addWidget(dialog)
    assert dialog.type_combo.count() == 6
    assert dialog.type_combo.findData("thematic") == -1 and dialog.type_combo.findData("notebook") == -1


@pytest.mark.parametrize("kind", ["thematic", "notebook"])
def test_dateless_disables_fields_and_switching_back_restores(qtbot, factory, kind):
    dialog = LessonDialog(1, factory, 5, after_lesson_id=3)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.topic_edit.setText("Дроби")
    dialog.homework_edit.setPlainText("§ 5")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(kind))
    for w in (dialog.date_edit, dialog.topic_edit, dialog.homework_edit):
        assert not w.isEnabled()
    assert dialog.topic_edit.text() == "" and dialog.homework_edit.toPlainText() == ""
    assert dialog.dateless_hint.isVisible()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("test"))
    for w in (dialog.date_edit, dialog.topic_edit, dialog.homework_edit):
        assert w.isEnabled()
    assert dialog.topic_edit.text() == "Дроби" and dialog.homework_edit.toPlainText() == "§ 5"
    assert not dialog.dateless_hint.isVisible()


@pytest.mark.parametrize("kind", ["thematic", "notebook"])
def test_create_column_calls_service_with_last_lesson(qtbot, factory, api, kind):
    dialog = LessonDialog(1, factory, 5, after_lesson_id=42)
    qtbot.addWidget(dialog)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(kind))
    dialog._on_submit()
    assert api.calls == [("column", 5, kind, 42)]
    assert dialog.result_column is not None and dialog.result_info is None


def test_no_lessons_inline_error(qtbot, factory, api):
    dialog = LessonDialog(1, factory, 5, after_lesson_id=None)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("thematic"))
    dialog._on_submit()
    assert dialog.error_label.isVisible()
    assert dialog.error_label.text() == "Спершу створіть урок у цьому семестрі"
    assert api.calls == [] and dialog.result_column is None


def test_service_error_inline(qtbot, factory, api):
    api.error = JournalError("Після цього уроку вже є такий стовпчик")
    dialog = LessonDialog(1, factory, 5, after_lesson_id=42)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("notebook"))
    dialog._on_submit()
    assert dialog.error_label.isVisible() and "вже є такий" in dialog.error_label.text()
    assert dialog.result_column is None

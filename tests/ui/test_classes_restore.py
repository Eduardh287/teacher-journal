"""Повернення класу з архіву при конфлікті семестрів (рецензія Fable, PR #11)."""
from contextlib import contextmanager
from datetime import date

from PySide6.QtWidgets import QMessageBox

from journal.services.auth_service import CurrentUser
from journal.services.class_service import ClassInfo
from journal.services.journal_types import LessonConflict, SemesterConflict
from journal.ui import classes_page
from journal.ui import service_scope as service_scope_module


def test_restore_conflict_shows_lessons_not_generic_error(qtbot, monkeypatch):
    conflict = SemesterConflict(
        [LessonConflict(1, "9-А", "2026-2027", "Алгебра", date(2027, 6, 15))]
    )

    class FakeClassService:
        def __init__(self, session):
            pass

        def set_class_archived(self, teacher_id, class_id, archived):
            raise conflict

        def list_classes(self, teacher_id, include_archived=False):
            return []

    @contextmanager
    def fake_scope():
        yield None

    monkeypatch.setattr(service_scope_module, "session_scope", fake_scope)
    monkeypatch.setattr(classes_page, "ClassService", FakeClassService)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: shown.append((title, text)))

    page = classes_page.ClassesPage(CurrentUser(1, "demo", "Демо Викладач"))
    qtbot.addWidget(page)
    page._current_class = ClassInfo(7, "9-А", "2026-2027", True, 0)
    monkeypatch.setattr(page, "_reload_detail", lambda: None)
    page._on_restore_class()

    assert len(shown) == 1
    title, text = shown[0]
    assert title == "Клас не повернуто з архіву"
    assert "9-А · Алгебра — 15.06.2027" in text
    assert text.endswith(
        "\n\nПісля повернення клас отримує загальні межі семестрів. Змініть їх у «Налаштування» → "
        "«Семестри» або перенесіть чи видаліть ці уроки в журналі (журнал архівного класу можна "
        "редагувати), а тоді поверніть клас ще раз."
    )
    assert "Налаштування журналу" not in text

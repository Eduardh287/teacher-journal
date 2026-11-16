"""Спільна обв'язка наскрізних тестів (tests/e2e) і QA-скрипта scripts/qa/screens.py.

Лише те, що не залежить від pytest: перенаправлення `session_scope` на SAVEPOINT однієї сесії,
підміна статичних QMessageBox і будівники даних. Фікстури лишаються в tests/e2e/conftest.py.
"""
import sys
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date

from PySide6.QtWidgets import QMessageBox
from sqlalchemy import select
from sqlalchemy.orm import Session

from journal import db
from journal.models import Subject, Teacher
from journal.services.auth_service import CurrentUser
from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService

MESSAGE_KINDS = ("warning", "information", "critical")
YEAR = "2026-2027"  # навчальний рік за замовчуванням для створених класів


def savepoint_scope(session: Session) -> Callable:
    """Замінник `journal.db.session_scope`: «commit» дії лише звільняє savepoint, «rollback» відкочує до нього."""

    @contextmanager
    def scope():
        with session.begin_nested():
            yield session

    return scope


def redirect_session_scope(scope: Callable, setter: Callable = setattr) -> None:
    """Підміняє `session_scope` у `journal.db` і в усіх модулях застосунку, що його імпортували.

    `setter` — `setattr` (скрипт) або `monkeypatch.setattr` (тести: підміна відкочується сама).
    """
    setter(db, "session_scope", scope)
    for name, module in list(sys.modules.items()):
        if name.startswith("journal.") and name != "journal.db" and hasattr(module, "session_scope"):
            setter(module, "session_scope", scope)


def stub_message_boxes(handler: Callable[[str, object, str, str], None], setter: Callable = setattr) -> None:
    """Статичні QMessageBox.warning/information/critical не блокують: їх приймає `handler(вид, parent, заголовок, текст)`."""
    for kind in MESSAGE_KINDS:

        def fake(parent=None, title="", text="", *args, _kind=kind, **kwargs):
            handler(_kind, parent, title, text)
            return QMessageBox.StandardButton.Ok

        setter(QMessageBox, kind, staticmethod(fake))


def add_teacher(session: Session, username: str = "demo_teacher", full_name: str = "Демо Викладач") -> CurrentUser:
    row = Teacher(username=username, password_hash="x", full_name=full_name)
    session.add(row)
    session.flush()
    return CurrentUser(row.id, row.username, row.full_name)


def subject_id(session: Session, name: str) -> int:
    return session.scalars(select(Subject.id).where(Subject.name == name)).one()


def make_class(session: Session, teacher_id: int, name: str, year: str = YEAR, students: list[str] | None = None):
    service = ClassService(session)
    info = service.create_class(teacher_id, name, year)
    if students:
        service.import_students(teacher_id, info.id, "\n".join(students))
    return info


def make_journal(session: Session, teacher_id: int, class_id: int, subject: str = "Алгебра"):
    return JournalService(session).create_journal(teacher_id, class_id, subject_id(session, subject))


def make_lesson(
    session: Session, teacher_id: int, journal_id: int, d: date, kind: str = "regular", topic: str | None = None
):
    return JournalService(session).create_lesson(teacher_id, journal_id, d, kind, topic)

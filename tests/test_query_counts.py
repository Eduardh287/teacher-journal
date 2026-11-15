"""Кількість SQL-запитів: відкриття журналу й редагування клітинки не мають повертатися до зайвих читань."""
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import event, select

from journal.models import Subject, Teacher
from journal.repositories.journal_repository import JournalRepository
from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService

# Було: get_grid 16, student_computed 8 (set_cell — 6, без змін). Збільшувати ці числа можна лише свідомо.
GET_GRID_QUERIES = 7
SET_CELL_QUERIES = 6
STUDENT_COMPUTED_QUERIES = 7


@contextmanager
def count_queries(session):
    """Лічильник SQL-запитів сесії; кеш сесії скидається, щоб рахувати «холодний» виклик (як у UI)."""
    session.flush()
    session.expunge_all()
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)


@pytest.fixture
def world(session):
    teacher = Teacher(username="pytest_qc", password_hash="x", full_name="Викладач")
    session.add(teacher)
    session.flush()
    classes, svc = ClassService(session), JournalService(session)
    school_class = classes.create_class(teacher.id, "9-А", "2026-2027")
    students = [classes.add_student(teacher.id, school_class.id, f"Учень {n}") for n in "АБВ"]
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = svc.create_journal(teacher.id, school_class.id, subject.id)
    lessons = [svc.create_lesson(teacher.id, journal.id, date(2026, 9, day)) for day in (1, 2, 3, 4)]
    lessons.append(svc.create_lesson(teacher.id, journal.id, date(2027, 2, 1)))
    svc.create_column(teacher.id, journal.id, "thematic", lessons[2].id)
    for lesson in lessons:
        for student in students:
            svc.set_cell(teacher.id, lesson.id, student.id, "present", 9, None)
    return svc, teacher, journal, students, lessons


def test_get_grid_query_count(session, world):
    svc, teacher, journal, _students, _lessons = world
    with count_queries(session) as statements:
        svc.get_grid(teacher.id, journal.id, 1)
    assert len(statements) == GET_GRID_QUERIES


def test_cell_edit_query_count(session, world):
    svc, teacher, journal, students, lessons = world
    with count_queries(session) as statements:
        svc.set_cell(teacher.id, lessons[0].id, students[0].id, "present", 10, None)
    assert len(statements) == SET_CELL_QUERIES
    with count_queries(session) as statements:
        svc.student_computed(teacher.id, journal.id, students[0].id)
    assert len(statements) == STUDENT_COMPUTED_QUERIES


def test_repository_filters_one_student(session, world):
    _svc, _teacher, journal, students, lessons = world
    repo = JournalRepository(session)
    entries = repo.entries([lesson.id for lesson in lessons], students[0].id)
    assert len(entries) == len(lessons) and {e.student_id for e in entries} == {students[0].id}


def test_student_computed_matches_grid(session, world):
    svc, teacher, journal, students, _lessons = world
    for semester in (1, 2):
        grid = svc.get_grid(teacher.id, journal.id, semester)
        for student in students:
            row = svc.student_computed(teacher.id, journal.id, student.id)
            shown = {k: v for (sid, k), v in grid.computed.items() if sid == student.id}
            assert shown and shown == {k: row[k] for k in shown}

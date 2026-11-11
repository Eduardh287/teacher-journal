"""Спільні фікстури: кожен тест працює в транзакції, яка завжди відкочується."""
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from journal.db import engine
from journal.models import Journal, SchoolClass, Student, Subject, Teacher


@pytest.fixture
def session():
    """Сесія в SAVEPOINT-режимі: зовнішня транзакція відкочується, дані в БД не лишаються."""
    connection = engine.connect()
    outer = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        connection.close()


@dataclass
class TeacherClass:
    teacher: Teacher
    school_class: SchoolClass
    students: list[Student]
    journal: Journal


@pytest.fixture
def teacher_class(session) -> TeacherClass:
    """Викладач, клас 9-А (2026-2027) з 2 учнями та журнал з математики."""
    teacher = Teacher(username="test_teacher", password_hash="x", full_name="Тест Викладач")
    school_class = SchoolClass(teacher=teacher, name="9-А", school_year="2026-2027")
    students = [
        Student(school_class=school_class, full_name="Учень Перший", position=1),
        Student(school_class=school_class, full_name="Учень Другий", position=2),
    ]
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = Journal(school_class=school_class, subject=subject)
    session.add_all([teacher, school_class, *students, journal])
    session.flush()
    return TeacherClass(teacher, school_class, students, journal)

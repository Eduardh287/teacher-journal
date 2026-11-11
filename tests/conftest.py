"""Спільні фікстури.

Тести працюють ТІЛЬКИ з окремою базою TEST_DATABASE_URL (journal_test) — робоча база
з даними учнів не використовується ніколи. Перед тестами до тестової бази
застосовуються міграції Alembic, а кожен тест іде в транзакції з відкатом.
"""
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from journal import db
from journal.config import PROJECT_ROOT, test_database_url
from journal.models import Journal, SchoolClass, Student, Subject, Teacher


@pytest.fixture(scope="session")
def engine():
    """Engine тестової бази з актуальною схемою (alembic upgrade head)."""
    url = test_database_url()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["skip_logging_config"] = True
    command.upgrade(cfg, "head")
    test_engine = db.init_engine(url)  # session_scope() у коді теж дивиться в тестову базу
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine):
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

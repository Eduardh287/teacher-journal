"""Тести переходу на новий навчальний рік (RolloverService)."""
from datetime import date

import pytest
from sqlalchemy import select

from journal.models import Journal, Student, Subject, Teacher
from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService
from journal.services.rollover_service import RolloverService
from journal.services.semesters import SemesterBoundaries
from journal.services.settings_service import SettingsService

YEAR = "2026-2027"
AUGUST = date(2027, 8, 1)


@pytest.fixture
def teacher(session):
    t = Teacher(username="pytest_roll", password_hash="x", full_name="R")
    session.add(t)
    session.flush()
    return t


@pytest.fixture
def classes(session):
    return ClassService(session)


@pytest.fixture
def journals(session):
    return JournalService(session)


@pytest.fixture
def roll(session):
    return RolloverService(session)


def subject_id(session, name):
    return session.scalars(select(Subject).where(Subject.name == name)).one().id


def make_class(classes, teacher, name, students=(), year=YEAR):
    c = classes.create_class(teacher.id, name, year)
    for s in students:
        classes.add_student(teacher.id, c.id, s)
    return c


def test_nothing_before_august(roll, classes, teacher):
    make_class(classes, teacher, "9-А", ["Іваненко Іван"])
    assert roll.plan(teacher.id, date(2027, 7, 31)) == []
    assert roll.apply(teacher.id, date(2027, 7, 31)) == []
    assert [c.name for c in classes.list_classes(teacher.id)] == ["9-А"]


def test_plan_actions(roll, classes, journals, teacher, session):
    c9 = make_class(classes, teacher, "9-А", ["Іваненко Іван", "Андрієнко Оля"])
    make_class(classes, teacher, "11-Б")
    make_class(classes, teacher, "Гурток")
    make_class(classes, teacher, "10-А")
    make_class(classes, teacher, "11-А", year="2027-2028")  # цільовий клас для 10-А вже є
    journals.create_journal(teacher.id, c9.id, subject_id(session, "Фізика"))
    journals.create_journal(teacher.id, c9.id, subject_id(session, "Алгебра"))
    items = {i.class_name: i for i in roll.plan(teacher.id, AUGUST)}
    assert set(items) == {"9-А", "11-Б", "Гурток", "10-А"}  # клас 11-А (2027-2028) ще не завершений
    nine = items["9-А"]
    assert (nine.action, nine.new_name, nine.new_year, nine.target_exists) == (
        "promote", "10-А", "2027-2028", False,
    )
    assert nine.student_count == 2 and nine.subject_names == ("Алгебра", "Фізика")
    assert items["11-Б"].action == "archive" and items["11-Б"].new_name is None
    assert items["Гурток"].action == "archive"
    assert items["10-А"].action == "promote" and items["10-А"].target_exists
    assert items["10-А"].new_name == "11-А"


def test_apply_promotes_copies_active_students_only(roll, classes, journals, teacher, session):
    c = make_class(classes, teacher, "9-А", ["Бойко Ганна", "Андрієнко Оля", "Мельник Петро"])
    old_students = classes.list_students(teacher.id, c.id)
    leaver = next(s for s in old_students if s.full_name.startswith("Мельник"))
    classes.set_student_archived(teacher.id, leaver.id, True)
    journal = journals.create_journal(teacher.id, c.id, subject_id(session, "Алгебра"))
    lesson = journals.create_lesson(teacher.id, journal.id, date(2026, 9, 3))
    old_ids = {s.id for s in old_students}

    items = roll.apply(teacher.id, AUGUST)

    assert [i.action for i in items] == ["promote"]
    active = {x.name: x for x in classes.list_classes(teacher.id)}
    assert set(active) == {"10-А"} and active["10-А"].school_year == "2027-2028"
    new_students = classes.list_students(teacher.id, active["10-А"].id)
    assert [(s.full_name, s.position) for s in new_students] == [("Андрієнко Оля", 1), ("Бойко Ганна", 2)]
    assert not ({s.id for s in new_students} & old_ids)  # нові записи
    assert all(not s.archived for s in new_students)
    archived = [x for x in classes.list_classes(teacher.id, include_archived=True) if x.archived]
    assert [(x.name, x.school_year) for x in archived] == [("9-А", YEAR)]
    # Старий журнал і його уроки на місці, нових журналів немає.
    assert journals.list_journals(teacher.id) == []
    old_journals = journals.list_journals(teacher.id, include_archived=True)
    assert len(old_journals) == 1 and old_journals[0].lesson_count == 1
    assert journals.get_grid(teacher.id, journal.id, 1).lessons[0].id == lesson.id


def test_apply_copy_journals_creates_empty_journals(roll, classes, journals, teacher, session):
    c = make_class(classes, teacher, "8-А", ["Іваненко Іван"])
    journals.create_journal(teacher.id, c.id, subject_id(session, "Алгебра"))
    journals.create_journal(teacher.id, c.id, subject_id(session, "Геометрія"))
    custom = SemesterBoundaries(8, 12, 1, 5)
    SettingsService(session).set_semesters(teacher.id, custom)

    roll.apply(teacher.id, AUGUST, copy_journals=True)

    new = journals.list_journals(teacher.id)
    assert sorted(j.subject_name for j in new) == ["Алгебра", "Геометрія"]
    assert all(j.class_name == "9-А" and j.lesson_count == 0 and j.boundaries == custom for j in new)


def test_apply_without_copy_journals_leaves_none(roll, classes, journals, teacher, session):
    c = make_class(classes, teacher, "8-А", ["Іваненко Іван"])
    journals.create_journal(teacher.id, c.id, subject_id(session, "Алгебра"))
    roll.apply(teacher.id, AUGUST)
    assert journals.list_journals(teacher.id) == []


def test_apply_eleventh_and_nonnumeric_archived(roll, classes, teacher):
    make_class(classes, teacher, "11-А", ["Іваненко Іван"])
    make_class(classes, teacher, "Гурток", ["Петренко Іван"])
    roll.apply(teacher.id, AUGUST)
    assert classes.list_classes(teacher.id) == []
    assert all(c.archived for c in classes.list_classes(teacher.id, include_archived=True))
    assert len(classes.list_classes(teacher.id, include_archived=True)) == 2


def test_apply_target_exists_only_archives(roll, classes, journals, teacher, session):
    c = make_class(classes, teacher, "9-А", ["Іваненко Іван"])
    journals.create_journal(teacher.id, c.id, subject_id(session, "Алгебра"))
    existing = make_class(classes, teacher, "10-А", ["Інший Учень"], year="2027-2028")
    roll.apply(teacher.id, AUGUST, copy_journals=True)
    assert [x.name for x in classes.list_classes(teacher.id)] == ["10-А"]
    assert [s.full_name for s in classes.list_students(teacher.id, existing.id)] == ["Інший Учень"]
    assert journals.list_journals(teacher.id) == []  # у наявний клас нічого не додаємо


def test_apply_is_idempotent(roll, classes, teacher, session):
    make_class(classes, teacher, "9-А", ["Іваненко Іван"])
    roll.apply(teacher.id, AUGUST)
    count = session.scalar(select(Student.id).order_by(Student.id.desc()).limit(1))
    assert roll.apply(teacher.id, AUGUST) == []
    assert session.scalar(select(Student.id).order_by(Student.id.desc()).limit(1)) == count
    assert len(classes.list_classes(teacher.id, include_archived=True)) == 2


def test_other_teacher_untouched(roll, classes, teacher, session):
    other = Teacher(username="pytest_roll2", password_hash="x", full_name="O")
    session.add(other)
    session.flush()
    make_class(classes, other, "9-А", ["Іваненко Іван"])
    assert roll.plan(teacher.id, AUGUST) == []
    roll.apply(teacher.id, AUGUST)
    assert [c.name for c in classes.list_classes(other.id)] == ["9-А"]


def test_new_journals_unique_per_subject(roll, classes, journals, teacher, session):
    c = make_class(classes, teacher, "5-А")
    journals.create_journal(teacher.id, c.id, subject_id(session, "Математика"))
    roll.apply(teacher.id, AUGUST, copy_journals=True)
    assert session.scalar(select(Journal.id).join(Subject).where(Subject.name == "Математика").limit(1))
    assert [j.class_name for j in journals.list_journals(teacher.id)] == ["6-А"]

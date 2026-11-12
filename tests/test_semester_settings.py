"""Тести етапу 5.2: налаштування меж семестрів, журнали архівних класів, повернення класу."""
from datetime import date

import pytest
from sqlalchemy import select

from journal.models import Journal, Lesson, Subject, Teacher
from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService
from journal.services.journal_types import JournalError, SemesterConflict
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries, SemesterError
from journal.services.settings_service import SettingsService

YEAR = "2026-2027"
AUG = SemesterBoundaries(8, 12, 1, 6)       # I починається в серпні
SHORT = SemesterBoundaries(9, 11, 2, 5)     # грудень, січень і червень — канікули


def make_teacher(session, suffix):
    teacher = Teacher(username=f"pytest_s_{suffix}", password_hash="x", full_name=suffix)
    session.add(teacher)
    session.flush()
    return teacher


def subject_id(session, name="Математика"):
    return session.scalars(select(Subject).where(Subject.name == name)).one().id


@pytest.fixture
def teacher(session):
    return make_teacher(session, "a")


@pytest.fixture
def svc(session):
    return JournalService(session)


@pytest.fixture
def classes(session):
    return ClassService(session)


@pytest.fixture
def settings(session):
    return SettingsService(session)


@pytest.fixture
def journal(svc, classes, teacher, session):
    c = classes.create_class(teacher.id, "9-А", YEAR)
    return svc.create_journal(teacher.id, c.id, subject_id(session))


def lesson_semester(session, lesson_id):
    return session.get(Lesson, lesson_id).semester


def test_get_semesters_defaults(settings, teacher):
    assert settings.get_semesters(teacher.id) == DEFAULT_BOUNDARIES


def test_set_semesters_recomputes_lessons(settings, svc, teacher, journal, session):
    lesson = svc.create_lesson(teacher.id, journal.id, date(2026, 9, 1))
    session.get(Lesson, lesson.id).semester = 2  # зіпсований стан: має виправитися перерахунком
    session.flush()
    new = SemesterBoundaries(9, 11, 1, 5)
    assert settings.set_semesters(teacher.id, new) == 1
    assert lesson_semester(session, lesson.id) == 1
    assert settings.get_semesters(teacher.id) == new
    assert svc.list_journals(teacher.id)[0].boundaries == new


def test_set_semesters_conflict_saves_nothing(settings, svc, classes, teacher, journal, session):
    keep = svc.create_lesson(teacher.id, journal.id, date(2026, 10, 1))
    svc.create_lesson(teacher.id, journal.id, date(2027, 6, 5))
    svc.create_lesson(teacher.id, journal.id, date(2026, 12, 20))
    c10 = classes.create_class(teacher.id, "10-Б", YEAR)
    j10 = svc.create_journal(teacher.id, c10.id, subject_id(session, "Фізика"))
    svc.create_lesson(teacher.id, j10.id, date(2027, 1, 12))
    with pytest.raises(SemesterConflict) as info:
        settings.set_semesters(teacher.id, SHORT)
    got = [(c.class_name, c.subject_name, c.lesson_date) for c in info.value.conflicts]
    assert got == [
        ("9-А", "Математика", date(2026, 12, 20)),
        ("9-А", "Математика", date(2027, 6, 5)),
        ("10-Б", "Фізика", date(2027, 1, 12)),
    ]
    assert settings.get_semesters(teacher.id) == DEFAULT_BOUNDARIES
    assert all(j.boundaries == DEFAULT_BOUNDARIES for j in svc.list_journals(teacher.id))
    assert lesson_semester(session, keep.id) == 1


def test_set_semesters_invalid_boundaries(settings, teacher):
    with pytest.raises(SemesterError):
        settings.set_semesters(teacher.id, SemesterBoundaries(1, 6, 9, 12))


def test_set_semesters_skips_archived_and_other_teacher(settings, svc, classes, teacher, journal, session):
    svc.create_lesson(teacher.id, journal.id, date(2027, 6, 20))  # у SHORT це канікули
    classes.set_class_archived(teacher.id, journal.class_id, True)
    other = make_teacher(session, "b")
    oc = classes.create_class(other.id, "9-А", YEAR)
    oj = svc.create_journal(other.id, oc.id, subject_id(session))
    assert settings.set_semesters(teacher.id, SHORT) == 0  # архівний журнал не чіпаємо
    assert svc.get_grid(teacher.id, journal.id, 2).journal.boundaries == DEFAULT_BOUNDARIES
    assert settings.get_semesters(other.id) == DEFAULT_BOUNDARIES
    assert session.get(Journal, oj.id).s1_end_month == 12


def test_create_journal_copies_teacher_boundaries(settings, svc, classes, teacher, session):
    settings.set_semesters(teacher.id, AUG)
    c = classes.create_class(teacher.id, "8-А", YEAR)
    info = svc.create_journal(teacher.id, c.id, subject_id(session))
    assert info.boundaries == AUG
    assert svc.create_lesson(teacher.id, info.id, date(2026, 8, 25)).semester == 1


def test_vacation_lesson_is_journal_error(svc, teacher, journal):
    with pytest.raises(JournalError):
        svc.create_lesson(teacher.id, journal.id, date(2026, 8, 25))  # типові межі: серпень — канікули


def test_set_journal_semesters_archived_ok(svc, classes, teacher, journal):
    lesson = svc.create_lesson(teacher.id, journal.id, date(2026, 10, 1))
    classes.set_class_archived(teacher.id, journal.class_id, True)
    new = SemesterBoundaries(10, 12, 1, 6)
    info = svc.set_journal_semesters(teacher.id, journal.id, new)
    assert info.boundaries == new and info.class_archived
    assert svc.get_grid(teacher.id, journal.id, 1).lessons[0].id == lesson.id


def test_set_journal_semesters_active_refused(svc, teacher, journal):
    with pytest.raises(JournalError, match="Налаштуваннях"):
        svc.set_journal_semesters(teacher.id, journal.id, AUG)


def test_set_journal_semesters_conflict_and_invalid(svc, classes, teacher, journal):
    svc.create_lesson(teacher.id, journal.id, date(2026, 12, 1))
    classes.set_class_archived(teacher.id, journal.class_id, True)
    with pytest.raises(SemesterConflict) as info:
        svc.set_journal_semesters(teacher.id, journal.id, SHORT)
    assert [c.lesson_date for c in info.value.conflicts] == [date(2026, 12, 1)]
    with pytest.raises(JournalError):
        svc.set_journal_semesters(teacher.id, journal.id, SemesterBoundaries(1, 6, 9, 12))
    assert svc.list_journals(teacher.id, include_archived=True)[0].boundaries == DEFAULT_BOUNDARIES


def test_set_journal_semesters_foreign_teacher(svc, journal, session):
    other = make_teacher(session, "b")
    with pytest.raises(JournalError):
        svc.set_journal_semesters(other.id, journal.id, DEFAULT_BOUNDARIES)


def test_delete_journal_on_archived_class_refused(svc, classes, teacher, journal):
    classes.set_class_archived(teacher.id, journal.class_id, True)
    with pytest.raises(JournalError, match="архів"):
        svc.delete_journal(teacher.id, journal.id)


def test_restore_class_resyncs_to_global(settings, svc, classes, teacher, journal):
    svc.create_lesson(teacher.id, journal.id, date(2026, 10, 1))
    classes.set_class_archived(teacher.id, journal.class_id, True)
    svc.set_journal_semesters(teacher.id, journal.id, SemesterBoundaries(10, 12, 1, 6))
    settings.set_semesters(teacher.id, AUG)
    classes.set_class_archived(teacher.id, journal.class_id, False)
    assert svc.list_journals(teacher.id)[0].boundaries == AUG


def test_restore_class_conflict_refused(settings, svc, classes, teacher, journal):
    svc.create_lesson(teacher.id, journal.id, date(2026, 12, 15))
    classes.set_class_archived(teacher.id, journal.class_id, True)
    settings.set_semesters(teacher.id, SHORT)
    with pytest.raises(SemesterConflict):
        classes.set_class_archived(teacher.id, journal.class_id, False)
    assert classes.list_classes(teacher.id) == []  # клас лишився в архіві

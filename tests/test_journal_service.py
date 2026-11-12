"""Тести JournalService: власність, журнали, уроки, таблиця, клітинки."""
from datetime import date

import pytest
from sqlalchemy import func, select

from journal.models import Journal, Lesson, LessonEntry, Subject, Teacher
from journal.services.class_service import ClassService
from journal.services.journal_service import JournalService
from journal.services.journal_types import (
    JournalError,
    JournalNotFound,
    LessonNotFound,
    semester_for_date,
)

YEAR = "2026-2027"
D1 = date(2026, 9, 1)   # 1 семестр
D2 = date(2027, 2, 1)   # 2 семестр


# ---------- допоміжне ----------


def make_teacher(session, suffix):
    teacher = Teacher(username=f"pytest_j_{suffix}", password_hash="x", full_name=f"Викладач {suffix}")
    session.add(teacher)
    session.flush()
    return teacher


def subject_id(session, name="Математика"):
    return session.scalars(select(Subject).where(Subject.name == name)).one().id


@pytest.fixture
def svc(session):
    return JournalService(session)


@pytest.fixture
def classes(session):
    return ClassService(session)


@pytest.fixture
def teacher(session):
    return make_teacher(session, "a")


@pytest.fixture
def other(session):
    return make_teacher(session, "b")


@pytest.fixture
def klass(classes, teacher):
    c = classes.create_class(teacher.id, "9-А", YEAR)
    classes.add_student(teacher.id, c.id, "Бондаренко Олена")
    classes.add_student(teacher.id, c.id, "Андрієнко Іван")
    return c


@pytest.fixture
def journal(svc, teacher, klass, session):
    return svc.create_journal(teacher.id, klass.id, subject_id(session))


@pytest.fixture
def lesson(svc, teacher, journal):
    return svc.create_lesson(teacher.id, journal.id, D1)


@pytest.fixture
def student_ids(classes, teacher, klass):
    return [s.id for s in classes.list_students(teacher.id, klass.id)]  # за алфавітом


# ---------- semester_for_date ----------


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 9, 1), 1), (date(2026, 12, 31), 1),
        (date(2027, 1, 1), 2), (date(2027, 6, 30), 2),
    ],
)
def test_semester_for_date(d, expected):
    assert semester_for_date(d) == expected


@pytest.mark.parametrize("d", [date(2027, 7, 1), date(2027, 8, 31)])
def test_semester_for_date_summer(d):
    with pytest.raises(JournalError):
        semester_for_date(d)


# ---------- журнали ----------


def test_create_and_list_journals(svc, classes, teacher, session):
    c10 = classes.create_class(teacher.id, "10-А", YEAR)
    c9 = classes.create_class(teacher.id, "9-А", YEAR)
    math, phys = subject_id(session), subject_id(session, "Фізика")
    svc.create_journal(teacher.id, c10.id, math)
    svc.create_journal(teacher.id, c9.id, phys)
    svc.create_journal(teacher.id, c9.id, math)
    names = [(j.class_name, j.subject_name) for j in svc.list_journals(teacher.id)]
    assert names == [("9-А", "Математика"), ("9-А", "Фізика"), ("10-А", "Математика")]


def test_list_journals_archived_filter(svc, classes, teacher, klass, journal):
    classes.set_class_archived(teacher.id, klass.id, True)
    assert svc.list_journals(teacher.id) == []
    shown = svc.list_journals(teacher.id, include_archived=True)
    assert len(shown) == 1 and shown[0].class_archived


def test_list_journals_lesson_count(svc, teacher, journal):
    svc.create_lesson(teacher.id, journal.id, D1)
    svc.create_lesson(teacher.id, journal.id, D2)
    assert svc.list_journals(teacher.id)[0].lesson_count == 2


def test_list_journals_other_teacher_sees_nothing(svc, other, journal):
    assert svc.list_journals(other.id, include_archived=True) == []


def test_candidates(svc, classes, teacher, session, klass):
    math, phys = subject_id(session), subject_id(session, "Фізика")
    assert {(c.class_id, c.subject_id) for c in svc.list_journal_candidates(teacher.id)} == {
        (klass.id, math), (klass.id, phys)
    }
    svc.create_journal(teacher.id, klass.id, math)
    assert [(c.class_id, c.subject_id) for c in svc.list_journal_candidates(teacher.id)] == [
        (klass.id, phys)
    ]
    classes.set_class_archived(teacher.id, klass.id, True)
    assert svc.list_journal_candidates(teacher.id) == []


def test_create_journal_duplicate(svc, teacher, klass, journal):
    with pytest.raises(JournalError, match="Такий журнал уже існує"):
        svc.create_journal(teacher.id, klass.id, journal.subject_id)


def test_create_journal_archived_class(svc, classes, teacher, klass, session):
    classes.set_class_archived(teacher.id, klass.id, True)
    with pytest.raises(JournalError, match="Клас в архіві — спершу поверніть його"):
        svc.create_journal(teacher.id, klass.id, subject_id(session))


def test_create_journal_foreign_class(svc, other, klass, session):
    with pytest.raises(JournalError):
        svc.create_journal(other.id, klass.id, subject_id(session))


def test_delete_journal_empty(svc, session, teacher, journal):
    svc.delete_journal(teacher.id, journal.id)
    assert session.get(Journal, journal.id) is None


def test_delete_journal_with_lessons_refused(svc, teacher, journal, lesson):
    with pytest.raises(JournalError, match="У журналі є уроки чи оцінки"):
        svc.delete_journal(teacher.id, journal.id)


def test_delete_journal_with_final_grades_refused(svc, session, teacher, journal, student_ids):
    from journal.models import FinalGrade, FinalGradeKind

    session.add(FinalGrade(journal_id=journal.id, student_id=student_ids[0],
                           kind=FinalGradeKind.ANNUAL, grade=9))
    session.flush()
    with pytest.raises(JournalError, match="У журналі є уроки чи оцінки"):
        svc.delete_journal(teacher.id, journal.id)


# ---------- власність ----------


def test_ownership_everywhere(svc, other, journal, lesson, student_ids):
    with pytest.raises(JournalNotFound, match="Журнал не знайдено"):
        svc.delete_journal(other.id, journal.id)
    with pytest.raises(JournalNotFound):
        svc.get_grid(other.id, journal.id, 1)
    with pytest.raises(JournalNotFound):
        svc.create_lesson(other.id, journal.id, D1)
    with pytest.raises(LessonNotFound, match="Урок не знайдено"):
        svc.update_lesson(other.id, lesson.id, D1, "regular", None)
    with pytest.raises(LessonNotFound):
        svc.delete_lesson(other.id, lesson.id)
    with pytest.raises(LessonNotFound):
        svc.set_cell(other.id, lesson.id, student_ids[0], "present", 5, None)


def test_missing_objects(svc, teacher):
    with pytest.raises(JournalNotFound):
        svc.get_grid(teacher.id, 999999, 1)
    with pytest.raises(LessonNotFound):
        svc.delete_lesson(teacher.id, 999999)


# ---------- уроки ----------


def test_create_lesson_fields(svc, teacher, journal):
    info = svc.create_lesson(teacher.id, journal.id, D2, "test", "  Тема  ")
    assert (info.semester, info.lesson_type, info.topic, info.entry_count) == (2, "test", "Тема", 0)


def test_topic_empty_and_too_long(svc, teacher, journal):
    assert svc.create_lesson(teacher.id, journal.id, D1, topic="   ").topic is None
    with pytest.raises(JournalError):
        svc.create_lesson(teacher.id, journal.id, D1, topic="а" * 256)
    assert svc.create_lesson(teacher.id, journal.id, D1, topic="а" * 255).topic == "а" * 255


@pytest.mark.parametrize("d", [date(2026, 8, 31), date(2027, 7, 1), date(2025, 9, 1),
                               date(2027, 9, 1), date(2026, 2, 1), date(2027, 10, 1)])
def test_lesson_date_outside_school_year(svc, teacher, journal, d):
    with pytest.raises(JournalError):
        svc.create_lesson(teacher.id, journal.id, d)


def test_lesson_date_outside_year_message(svc, teacher, journal):
    with pytest.raises(JournalError, match="Дата не належить навчальному року 2026-2027"):
        svc.create_lesson(teacher.id, journal.id, date(2025, 10, 1))


def test_year_boundaries_accepted(svc, teacher, journal):
    assert svc.create_lesson(teacher.id, journal.id, date(2026, 12, 31)).semester == 1
    assert svc.create_lesson(teacher.id, journal.id, date(2027, 1, 1)).semester == 2


def test_two_lessons_same_day_ordered_by_id(svc, teacher, journal):
    a = svc.create_lesson(teacher.id, journal.id, D1)
    b = svc.create_lesson(teacher.id, journal.id, D1)
    earlier = svc.create_lesson(teacher.id, journal.id, date(2026, 9, 1))
    grid = svc.get_grid(teacher.id, journal.id, 1)
    assert [x.id for x in grid.lessons] == [a.id, b.id, earlier.id]


def test_lessons_ordered_by_date(svc, teacher, journal):
    late = svc.create_lesson(teacher.id, journal.id, date(2026, 10, 5))
    early = svc.create_lesson(teacher.id, journal.id, date(2026, 9, 5))
    grid = svc.get_grid(teacher.id, journal.id, 1)
    assert [x.id for x in grid.lessons] == [early.id, late.id]


def test_update_lesson_moves_semester(svc, teacher, journal, lesson):
    info = svc.update_lesson(teacher.id, lesson.id, D2, "lab", " Нова ")
    assert (info.lesson_date, info.semester, info.lesson_type, info.topic) == (D2, 2, "lab", "Нова")
    with pytest.raises(JournalError):
        svc.update_lesson(teacher.id, lesson.id, date(2030, 1, 1), "lab", None)


def test_update_lesson_reports_entry_count(svc, teacher, lesson, student_ids):
    svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", 7, None)
    assert svc.update_lesson(teacher.id, lesson.id, D1, "regular", None).entry_count == 1


def test_delete_lesson_removes_entries(svc, session, teacher, lesson, student_ids):
    svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", 7, None)
    svc.set_cell(teacher.id, lesson.id, student_ids[1], "late", None, None)
    svc.delete_lesson(teacher.id, lesson.id)
    assert session.get(Lesson, lesson.id) is None
    left = session.scalar(
        select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id == lesson.id)
    )
    assert left == 0


def test_writes_on_archived_class_refused(svc, classes, teacher, klass, journal, lesson, student_ids):
    classes.set_class_archived(teacher.id, klass.id, True)
    msg = "Клас в архіві — журнал лише для перегляду"
    with pytest.raises(JournalError, match=msg):
        svc.create_lesson(teacher.id, journal.id, D1)
    with pytest.raises(JournalError, match=msg):
        svc.update_lesson(teacher.id, lesson.id, D1, "regular", None)
    with pytest.raises(JournalError, match=msg):
        svc.delete_lesson(teacher.id, lesson.id)
    with pytest.raises(JournalError, match=msg):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", 5, None)
    assert svc.get_grid(teacher.id, journal.id, 1).journal.class_archived  # читати можна


# ---------- get_grid ----------


def test_grid_content_and_semester_filter(svc, teacher, journal, student_ids):
    l1 = svc.create_lesson(teacher.id, journal.id, D1)
    l2 = svc.create_lesson(teacher.id, journal.id, D2)
    svc.set_cell(teacher.id, l1.id, student_ids[0], "present", 9, "ок")
    svc.set_cell(teacher.id, l2.id, student_ids[1], "sick", None, None)

    g1 = svc.get_grid(teacher.id, journal.id, 1)
    assert [s.full_name for s in g1.students] == ["Андрієнко Іван", "Бондаренко Олена"]
    assert [s.position for s in g1.students] == [1, 2]
    assert [x.id for x in g1.lessons] == [l1.id]
    assert g1.lessons[0].entry_count == 1
    assert list(g1.cells) == [(student_ids[0], l1.id)]
    cell = g1.cells[(student_ids[0], l1.id)]
    assert (cell.attendance, cell.grade, cell.comment) == ("present", 9, "ок")
    assert g1.journal.lesson_count == 2

    g2 = svc.get_grid(teacher.id, journal.id, 2)
    assert list(g2.cells) == [(student_ids[1], l2.id)]
    assert g2.cells[(student_ids[1], l2.id)].attendance == "sick"


def test_grid_bad_semester(svc, teacher, journal):
    for bad in (0, 3):
        with pytest.raises(JournalError):
            svc.get_grid(teacher.id, journal.id, bad)


def test_grid_archived_students(svc, classes, teacher, klass, journal, lesson, student_ids):
    """Вибулий учень без відміток зникає з таблиці, з відмітками — лишається в кінці."""
    with_marks, without = student_ids[0], student_ids[1]
    svc.set_cell(teacher.id, lesson.id, with_marks, "present", 6, None)
    classes.set_student_archived(teacher.id, with_marks, True)
    classes.set_student_archived(teacher.id, without, True)
    classes.add_student(teacher.id, klass.id, "Яковенко Петро")

    grid = svc.get_grid(teacher.id, journal.id, 1)
    assert [(s.full_name, s.archived) for s in grid.students] == [
        ("Яковенко Петро", False), ("Андрієнко Іван", True)
    ]


# ---------- set_cell ----------


def test_set_cell_insert_update_idempotent(svc, session, teacher, lesson, student_ids):
    sid = student_ids[0]
    first = svc.set_cell(teacher.id, lesson.id, sid, "present", 8, None)
    assert (first.attendance, first.grade, first.comment) == ("present", 8, None)
    again = svc.set_cell(teacher.id, lesson.id, sid, "present", 8, None)
    assert again == first
    updated = svc.set_cell(teacher.id, lesson.id, sid, "late", 10, "  спізнився  ")
    assert (updated.attendance, updated.grade, updated.comment) == ("late", 10, "спізнився")
    count = session.scalar(
        select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id == lesson.id)
    )
    assert count == 1


def test_set_cell_empty_state_deletes_row(svc, session, teacher, lesson, student_ids):
    sid = student_ids[0]
    svc.set_cell(teacher.id, lesson.id, sid, "present", 8, "к")
    assert svc.set_cell(teacher.id, lesson.id, sid, "present", None, "   ") is None
    assert session.get(LessonEntry, (lesson.id, sid)) is None
    # повторне очищення порожньої клітинки — теж None, без помилки
    assert svc.set_cell(teacher.id, lesson.id, sid, "present", None, None) is None


def test_set_cell_absent_without_grade_is_stored(svc, teacher, lesson, student_ids):
    cell = svc.set_cell(teacher.id, lesson.id, student_ids[0], "absent", None, None)
    assert cell.attendance == "absent"


def test_set_cell_comment_only_is_stored(svc, teacher, lesson, student_ids):
    cell = svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", None, "Лише коментар")
    assert (cell.attendance, cell.grade, cell.comment) == ("present", None, "Лише коментар")


@pytest.mark.parametrize("grade", [0, 13, -1, 100])
def test_set_cell_grade_range(svc, teacher, lesson, student_ids, grade):
    with pytest.raises(JournalError, match="Оцінка має бути від 1 до 12"):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", grade, None)


@pytest.mark.parametrize("grade", [1, 12])
def test_set_cell_grade_bounds_ok(svc, teacher, lesson, student_ids, grade):
    assert svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", grade, None).grade == grade


@pytest.mark.parametrize("attendance", ["absent", "sick"])
def test_set_cell_grade_with_absence_refused(svc, teacher, lesson, student_ids, attendance):
    with pytest.raises(JournalError, match="Відсутньому учню не можна поставити оцінку"):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], attendance, 5, None)


def test_set_cell_late_with_grade_ok(svc, teacher, lesson, student_ids):
    cell = svc.set_cell(teacher.id, lesson.id, student_ids[0], "late", 9, None)
    assert (cell.attendance, cell.grade) == ("late", 9)


def test_set_cell_foreign_student(svc, classes, teacher, other, lesson):
    foreign_class = classes.create_class(other.id, "9-А", YEAR)
    foreign = classes.add_student(other.id, foreign_class.id, "Чужий Учень")
    with pytest.raises(JournalError, match="Учня не знайдено"):
        svc.set_cell(teacher.id, lesson.id, foreign.id, "present", 5, None)
    with pytest.raises(JournalError, match="Учня не знайдено"):
        svc.set_cell(teacher.id, lesson.id, 999999, "present", 5, None)


def test_set_cell_student_of_other_own_class(svc, classes, teacher, lesson):
    """Учень іншого класу того ж викладача теж не належить цьому журналу."""
    other_class = classes.create_class(teacher.id, "9-Б", YEAR)
    stranger = classes.add_student(teacher.id, other_class.id, "Інший Клас")
    with pytest.raises(JournalError, match="Учня не знайдено"):
        svc.set_cell(teacher.id, lesson.id, stranger.id, "present", 5, None)


def test_set_cell_archived_student(svc, classes, teacher, lesson, student_ids):
    classes.set_student_archived(teacher.id, student_ids[0], True)
    with pytest.raises(JournalError, match="Учень вибув — його клітинки лише для перегляду"):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", 5, None)


def test_set_cell_comment_limits(svc, teacher, lesson, student_ids):
    ok = svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", None, "я" * 500)
    assert len(ok.comment) == 500
    with pytest.raises(JournalError):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], "present", None, "я" * 501)
    # обрізання пробілів іде до перевірки довжини
    assert svc.set_cell(teacher.id, lesson.id, student_ids[1], "present", None, " " + "я" * 500 + " ")


def test_set_cell_unknown_attendance(svc, teacher, lesson, student_ids):
    with pytest.raises(JournalError):
        svc.set_cell(teacher.id, lesson.id, student_ids[0], "maybe", None, None)  # type: ignore[arg-type]


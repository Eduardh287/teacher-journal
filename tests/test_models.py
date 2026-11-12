"""Тести моделей: обмеження БД, enum-и та каскадне видалення."""
from datetime import date

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from journal.models import (
    Attendance,
    FinalGrade,
    FinalGradeKind,
    Journal,
    Lesson,
    LessonEntry,
    SchoolClass,
    Student,
)


def make_lesson(session, tc, semester=1, d=date(2026, 9, 1)):
    lesson = Lesson(journal=tc.journal, lesson_date=d, semester=semester, topic="Тема")
    session.add(lesson)
    session.flush()
    return lesson


def test_entry_roundtrip(session, teacher_class):
    """Оцінка 10 і відвідування SICK зберігаються та читаються назад."""
    lesson = make_lesson(session, teacher_class)
    student = teacher_class.students[0]
    session.add(LessonEntry(lesson=lesson, student=student, grade=10, attendance=Attendance.SICK))
    session.flush()
    session.expire_all()
    entry = session.get(LessonEntry, (lesson.id, student.id))
    assert entry.grade == 10
    assert entry.attendance is Attendance.SICK


@pytest.mark.parametrize("grade", [0, 13])
def test_grade_out_of_range_rejected(session, teacher_class, grade):
    """Оцінки поза діапазоном 1-12 відхиляються."""
    lesson = make_lesson(session, teacher_class)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(LessonEntry(lesson=lesson, student=teacher_class.students[0], grade=grade))
            session.flush()


def test_grade_none_allowed(session, teacher_class):
    """Оцінка може бути порожньою (лише відвідування)."""
    lesson = make_lesson(session, teacher_class)
    student = teacher_class.students[0]
    session.add(LessonEntry(lesson=lesson, student=student, grade=None, attendance=Attendance.ABSENT))
    session.flush()
    session.expire_all()
    entry = session.get(LessonEntry, (lesson.id, student.id))
    assert entry.grade is None
    assert entry.attendance is Attendance.ABSENT


def test_duplicate_entry_rejected(session, teacher_class):
    """Другий запис для пари (урок, учень) неможливий."""
    lesson = make_lesson(session, teacher_class)
    student = teacher_class.students[0]
    session.add(LessonEntry(lesson=lesson, student=student, grade=5))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(
                insert(LessonEntry).values(lesson_id=lesson.id, student_id=student.id, grade=6)
            )


def test_lesson_semester_3_rejected(session, teacher_class):
    """Семестр може бути лише 1 або 2."""
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                Lesson(journal=teacher_class.journal, lesson_date=date(2026, 9, 2), semester=3)
            )
            session.flush()


def test_final_grades_semester_and_annual(session, teacher_class):
    """Семестрова та річна оцінки одного учня співіснують; дубль того ж виду відхиляється."""
    j, s = teacher_class.journal, teacher_class.students[0]
    session.add_all(
        [
            FinalGrade(journal=j, student=s, kind=FinalGradeKind.SEMESTER_1, grade=9),
            FinalGrade(journal=j, student=s, kind=FinalGradeKind.ANNUAL, grade=10),
        ]
    )
    session.flush()
    count = session.scalar(
        select(func.count()).select_from(FinalGrade).where(FinalGrade.journal_id == j.id)
    )
    assert count == 2
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(
                insert(FinalGrade).values(
                    journal_id=j.id, student_id=s.id, kind=FinalGradeKind.ANNUAL, grade=11
                )
            )


def test_delete_class_with_journal_restricted(session, teacher_class):
    """Клас із журналом видалити не можна: БД відмовляє (RESTRICT)."""
    session.delete(teacher_class.school_class)
    with pytest.raises(IntegrityError):
        session.flush()


def test_delete_class_with_students_only(session, teacher_class):
    """Клас без журналів видаляється разом з учнями."""
    tc = teacher_class
    session.delete(tc.journal)
    session.flush()
    class_id, student_ids = tc.school_class.id, [s.id for s in tc.students]
    session.expire_all()

    session.delete(session.get(SchoolClass, class_id))
    session.flush()
    session.expire_all()

    assert session.get(SchoolClass, class_id) is None
    count = session.scalar(select(func.count()).select_from(Student).where(Student.id.in_(student_ids)))
    assert count == 0


def test_delete_journal_with_lessons_restricted(session, teacher_class):
    """Журнал з уроками видалити не можна."""
    make_lesson(session, teacher_class)
    session.expire_all()
    session.delete(session.get(Journal, teacher_class.journal.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_delete_student_with_entry_restricted(session, teacher_class):
    """Учня з відміткою видалити не можна."""
    lesson = make_lesson(session, teacher_class)
    student = teacher_class.students[0]
    session.add(LessonEntry(lesson=lesson, student=student, grade=8))
    session.flush()
    session.delete(student)
    with pytest.raises(IntegrityError):
        session.flush()


def test_delete_lesson_cascades_to_entries(session, teacher_class):
    """Видалення уроку прибирає його клітинки."""
    lesson = make_lesson(session, teacher_class)
    session.add(LessonEntry(lesson=lesson, student=teacher_class.students[0], grade=8))
    session.flush()
    lesson_id = lesson.id
    session.delete(lesson)
    session.flush()
    session.expire_all()
    count = session.scalar(
        select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id == lesson_id)
    )
    assert count == 0


def test_lessons_ordered_by_date_then_id(session, teacher_class):
    """Journal.lessons віддає уроки за датою, а за однакової дати — за id."""
    late = make_lesson(session, teacher_class, d=date(2026, 9, 10))
    early = make_lesson(session, teacher_class, d=date(2026, 9, 2))
    same = make_lesson(session, teacher_class, d=date(2026, 9, 10))
    session.expire_all()
    ids = [lesson.id for lesson in session.get(Journal, teacher_class.journal.id).lessons]
    assert ids == [early.id, late.id, same.id]


def test_delete_teacher_cascades_to_classes(session, teacher_class):
    """Видалення викладача без журналів прибирає його класи та учнів."""
    class_id = teacher_class.school_class.id
    student_ids = [s.id for s in teacher_class.students]
    session.delete(teacher_class.journal)
    session.flush()
    session.expire_all()

    session.delete(teacher_class.teacher)
    session.flush()
    session.expire_all()

    assert session.get(SchoolClass, class_id) is None
    remaining = session.scalar(
        select(func.count()).select_from(Student).where(Student.id.in_(student_ids))
    )
    assert remaining == 0


def test_delete_teacher_with_journal_restricted(session, teacher_class):
    """Викладача, у класу якого є журнал, видалити не можна."""
    session.delete(teacher_class.teacher)
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_attendance_rejected_by_db(session, teacher_class):
    """Недопустиме значення відвідування відхиляє сама БД (CHECK-обмеження)."""
    lesson = make_lesson(session, teacher_class)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(
                insert(LessonEntry.__table__).values(
                    lesson_id=lesson.id, student_id=teacher_class.students[0].id, attendance="maybe"
                )
            )


def test_duplicate_class_name_same_year_rejected(session, teacher_class):
    """Той самий викладач не може мати два класи з однаковою назвою в одному році."""
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                SchoolClass(teacher_id=teacher_class.teacher.id, name="9-А", school_year="2026-2027")
            )
            session.flush()


def test_same_class_name_other_year_allowed(session, teacher_class):
    """Та сама назва в іншому навчальному році дозволена."""
    session.add(SchoolClass(teacher_id=teacher_class.teacher.id, name="9-А", school_year="2027-2028"))
    session.flush()

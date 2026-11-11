"""Тести ClassService та допоміжних функцій (класи, учні, імпорт, позиції, архів)."""
from datetime import date

import pytest
from sqlalchemy import func, select

from journal.models import (
    FinalGrade,
    FinalGradeKind,
    Journal,
    Lesson,
    LessonEntry,
    SchoolClass,
    Student,
    Subject,
    Teacher,
)
from journal.services.class_service import (
    ClassError,
    ClassService,
    ImportResult,
    default_school_year,
    parse_student_list,
    school_year_choices,
)
from journal.services.ua_sort import ukrainian_sort_key

YEAR = "2026-2027"


# ---------- допоміжне ----------


def make_teacher(session, suffix="a") -> Teacher:
    teacher = Teacher(username=f"pytest_{suffix}", password_hash="x", full_name=f"Викладач {suffix}")
    session.add(teacher)
    session.flush()
    return teacher


@pytest.fixture
def svc(session):
    return ClassService(session)


@pytest.fixture
def teacher(session):
    return make_teacher(session, "a")


@pytest.fixture
def other_teacher(session):
    return make_teacher(session, "b")


@pytest.fixture
def klass(svc, teacher):
    return svc.create_class(teacher.id, "9-А", YEAR)


def names(svc, teacher, class_id, archived=None):
    infos = svc.list_students(teacher.id, class_id)
    if archived is not None:
        infos = [s for s in infos if s.archived is archived]
    return [s.full_name for s in infos]


def assert_positions(svc, teacher, class_id):
    """Активні — 1..N в українському алфавітному порядку, вибулі — 0."""
    infos = svc.list_students(teacher.id, class_id)
    active = [s for s in infos if not s.archived]
    assert [s.position for s in active] == list(range(1, len(active) + 1))
    assert [s.full_name for s in active] == sorted(
        (s.full_name for s in active), key=ukrainian_sort_key
    )
    assert all(s.position == 0 for s in infos if s.archived)


def count_students(session, class_id) -> int:
    return session.scalar(select(func.count()).select_from(Student).where(Student.class_id == class_id))


def add_record_entry(session, student: Student, school_class_id: int):
    """Журнал з математики, урок і відмітка для учня."""
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = Journal(class_id=school_class_id, subject=subject)
    session.add(journal)
    session.flush()
    lesson = Lesson(journal=journal, lesson_date=date(2026, 9, 1), semester=1)
    session.add(lesson)
    session.flush()
    session.add(LessonEntry(lesson=lesson, student=student, grade=10))
    session.flush()
    return journal


# ---------- навчальний рік ----------


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 7, 31), "2025-2026"),
        (date(2026, 8, 1), "2026-2027"),
        (date(2026, 12, 31), "2026-2027"),
        (date(2027, 1, 1), "2026-2027"),
    ],
)
def test_default_school_year(today, expected):
    assert default_school_year(today) == expected


def test_school_year_choices():
    assert school_year_choices(date(2026, 11, 11)) == ["2025-2026", "2026-2027", "2027-2028"]
    assert school_year_choices(date(2026, 7, 1)) == ["2024-2025", "2025-2026", "2026-2027"]


@pytest.mark.parametrize("bad", ["2026/2027", "2026-2028", "abc"])
def test_invalid_school_year_rejected(svc, teacher, bad):
    with pytest.raises(ClassError):
        svc.create_class(teacher.id, "9-А", bad)


# ---------- назва класу ----------


def test_class_name_trimmed_and_collapsed(svc, teacher):
    info = svc.create_class(teacher.id, "  9   -  А  ", YEAR)
    assert info.name == "9 - А"


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_empty_class_name_rejected(svc, teacher, bad):
    with pytest.raises(ClassError):
        svc.create_class(teacher.id, bad, YEAR)


def test_class_name_length_limit(svc, teacher):
    with pytest.raises(ClassError):
        svc.create_class(teacher.id, "а" * 21, YEAR)
    assert svc.create_class(teacher.id, "а" * 20, YEAR).name == "а" * 20


# ---------- унікальність класу ----------


def test_duplicate_class_case_insensitive(svc, teacher):
    svc.create_class(teacher.id, "9-а", YEAR)
    with pytest.raises(ClassError):
        svc.create_class(teacher.id, "9-А", YEAR)


def test_duplicate_class_rejected_even_if_archived(svc, teacher):
    first = svc.create_class(teacher.id, "9-А", YEAR)
    svc.set_class_archived(teacher.id, first.id, True)
    with pytest.raises(ClassError):
        svc.create_class(teacher.id, "9-а", YEAR)


def test_same_name_other_year_allowed(svc, teacher):
    svc.create_class(teacher.id, "9-А", YEAR)
    svc.create_class(teacher.id, "9-А", "2027-2028")


def test_same_name_other_teacher_allowed(svc, teacher, other_teacher):
    svc.create_class(teacher.id, "9-А", YEAR)
    svc.create_class(other_teacher.id, "9-А", YEAR)


def test_update_class_to_duplicate_rejected(svc, teacher):
    svc.create_class(teacher.id, "9-А", YEAR)
    second = svc.create_class(teacher.id, "9-Б", YEAR)
    with pytest.raises(ClassError):
        svc.update_class(teacher.id, second.id, "9-а", YEAR)


def test_update_class_to_own_name_allowed(svc, teacher):
    info = svc.create_class(teacher.id, "9-А", YEAR)
    updated = svc.update_class(teacher.id, info.id, "9-А", YEAR)
    assert updated.name == "9-А"
    renamed = svc.update_class(teacher.id, info.id, "9-Б", "2027-2028")
    assert (renamed.name, renamed.school_year) == ("9-Б", "2027-2028")


# ---------- list_classes ----------


def test_list_classes_order(svc, teacher):
    for name in ["10-А", "5-Б", "9-А", "5-А"]:
        svc.create_class(teacher.id, name, YEAR)
    svc.create_class(teacher.id, "11-А", "2025-2026")
    result = svc.list_classes(teacher.id)
    assert [c.name for c in result] == ["5-А", "5-Б", "9-А", "10-А", "11-А"]
    assert result[-1].school_year == "2025-2026"


def test_list_classes_archived_hidden_by_default(svc, teacher):
    a = svc.create_class(teacher.id, "5-А", YEAR)
    svc.create_class(teacher.id, "5-Б", YEAR)
    svc.set_class_archived(teacher.id, a.id, True)
    assert [c.name for c in svc.list_classes(teacher.id)] == ["5-Б"]
    all_classes = svc.list_classes(teacher.id, include_archived=True)
    assert [c.name for c in all_classes] == ["5-А", "5-Б"]
    assert [c.archived for c in all_classes] == [True, False]


def test_list_classes_student_count_active_only(svc, teacher, klass):
    for n in ["Авраменко", "Борисенко", "Ващук"]:
        svc.add_student(teacher.id, klass.id, n)
    victim = [s for s in svc.list_students(teacher.id, klass.id) if s.full_name == "Ващук"][0]
    svc.set_student_archived(teacher.id, victim.id, True)
    assert svc.list_classes(teacher.id)[0].student_count == 2


def test_list_classes_only_own(svc, teacher, other_teacher, klass):
    assert svc.list_classes(other_teacher.id) == []


# ---------- володіння ----------


def test_foreign_class_access_denied(svc, teacher, other_teacher, klass):
    with pytest.raises(ClassError, match="Клас не знайдено"):
        svc.list_students(other_teacher.id, klass.id)
    with pytest.raises(ClassError, match="Клас не знайдено"):
        svc.add_student(other_teacher.id, klass.id, "Іваненко")
    with pytest.raises(ClassError, match="Клас не знайдено"):
        svc.update_class(other_teacher.id, klass.id, "9-Б", YEAR)
    with pytest.raises(ClassError, match="Клас не знайдено"):
        svc.delete_class(other_teacher.id, klass.id)


def test_foreign_student_access_denied(svc, teacher, other_teacher, klass):
    student = svc.add_student(teacher.id, klass.id, "Іваненко")
    with pytest.raises(ClassError, match="Учня не знайдено"):
        svc.rename_student(other_teacher.id, student.id, "Петренко")
    with pytest.raises(ClassError, match="Учня не знайдено"):
        svc.delete_student(other_teacher.id, student.id)
    with pytest.raises(ClassError, match="Учня не знайдено"):
        svc.set_student_archived(other_teacher.id, student.id, True)


# ---------- сортування ----------


def test_ukrainian_sort_order():
    assert ukrainian_sort_key("Гнатюк") < ukrainian_sort_key("Ґудзь") < ukrainian_sort_key("Данько")
    assert (
        ukrainian_sort_key("Иванна")
        < ukrainian_sort_key("Іваненко")
        < ukrainian_sort_key("Їжак")
        < ukrainian_sort_key("Йосипенко")
    )


def test_sort_key_ignores_apostrophe_and_case():
    assert ukrainian_sort_key("Д'ячук") == ukrainian_sort_key("Дячук")
    assert ukrainian_sort_key("Д’ячук") == ukrainian_sort_key("Дячук")
    assert ukrainian_sort_key("ІВАНЕНКО") == ukrainian_sort_key("іваненко")


def test_sort_key_space_before_letters():
    assert ukrainian_sort_key("Іван Петренко") < ukrainian_sort_key("Іваненко")


# ---------- розбір списку ----------


def test_parse_student_list_numbering():
    assert parse_student_list("1. A\n2) B\n3\tC") == ["A", "B", "C"]


def test_parse_student_list_whitespace_and_blank_lines():
    text = "   Іваненко   Петро  \n\n   \n\t\nПетренко\tОлена\n"
    assert parse_student_list(text) == ["Іваненко Петро", "Петренко Олена"]


@pytest.mark.parametrize("apostrophe", ["’", "ʼ", "`"])
def test_parse_student_list_apostrophes(apostrophe):
    assert parse_student_list(f"Д{apostrophe}ячук") == ["Д'ячук"]


# ---------- імпорт ----------


def test_import_skips_duplicates_in_paste_and_existing(svc, teacher, klass, session):
    svc.add_student(teacher.id, klass.id, "Іваненко Петро")
    gone = svc.add_student(teacher.id, klass.id, "Сидоренко Ігор")
    svc.set_student_archived(teacher.id, gone.id, True)
    text = "\n".join(
        [
            "1. Іваненко Петро",  # існуючий активний
            "2. сидоренко ігор",  # існуючий вибулий
            "3. Бондаренко Анна",
            "4. БОНДАРЕНКО АННА",  # дубль у вставці
            "5. Давиденко Олег",
        ]
    )
    result = svc.import_students(teacher.id, klass.id, text)
    assert result == ImportResult(added=2, skipped_duplicates=3)
    assert names(svc, teacher, klass.id, archived=False) == [
        "Бондаренко Анна",
        "Давиденко Олег",
        "Іваненко Петро",
    ]
    assert count_students(session, klass.id) == 4
    assert_positions(svc, teacher, klass.id)


def test_preview_import_matches_and_writes_nothing(svc, teacher, klass, session):
    svc.add_student(teacher.id, klass.id, "Іваненко Петро")
    text = "Іваненко Петро\nБондаренко Анна\nбондаренко анна\nДавиденко Олег"
    before = count_students(session, klass.id)
    preview = svc.preview_import(teacher.id, klass.id, text)
    assert count_students(session, klass.id) == before
    assert preview == ImportResult(added=2, skipped_duplicates=2)
    assert svc.import_students(teacher.id, klass.id, text) == preview


def test_import_line_too_long(svc, teacher, klass, session):
    text = "Іваненко Петро\nБондаренко Анна\n" + "а" * 151
    with pytest.raises(ClassError, match="3"):
        svc.import_students(teacher.id, klass.id, text)
    assert count_students(session, klass.id) == 0


def test_import_exceeding_limit_adds_nothing(svc, teacher, klass, session):
    first = "\n".join(f"Учень{'а' * (i % 20)}{chr(1072 + i // 20)} {i}" for i in range(40))
    svc.import_students(teacher.id, klass.id, first)
    assert count_students(session, klass.id) == 40
    more = "\n".join(f"Інший{i}" for i in range(21))
    with pytest.raises(ClassError):
        svc.import_students(teacher.id, klass.id, more)
    assert count_students(session, klass.id) == 40
    # рівно 60 — дозволено
    assert svc.import_students(teacher.id, klass.id, "\n".join(f"Інший{i}" for i in range(20))).added == 20


# ---------- позиції ----------


def test_positions_after_add_import_rename_delete_archive_restore(svc, teacher, klass):
    cid = klass.id
    svc.add_student(teacher.id, cid, "Петренко")
    assert_positions(svc, teacher, cid)
    svc.add_student(teacher.id, cid, "Ґудзь")
    svc.add_student(teacher.id, cid, "Андрієнко")
    assert_positions(svc, teacher, cid)
    svc.import_students(teacher.id, cid, "1. Мельник\n2. Ящук\n3. Іваненко")
    assert_positions(svc, teacher, cid)

    yashchuk = next(s for s in svc.list_students(teacher.id, cid) if s.full_name == "Ящук")
    assert yashchuk.position == 6
    renamed = svc.rename_student(teacher.id, yashchuk.id, "Абрамович")
    assert renamed.position == 1
    assert_positions(svc, teacher, cid)

    petrenko = next(s for s in svc.list_students(teacher.id, cid) if s.full_name == "Петренко")
    svc.delete_student(teacher.id, petrenko.id)
    assert_positions(svc, teacher, cid)

    melnyk = next(s for s in svc.list_students(teacher.id, cid) if s.full_name == "Мельник")
    svc.set_student_archived(teacher.id, melnyk.id, True)
    assert_positions(svc, teacher, cid)
    svc.set_student_archived(teacher.id, melnyk.id, False)
    assert_positions(svc, teacher, cid)


def test_list_students_active_then_archived(svc, teacher, klass):
    cid = klass.id
    svc.import_students(teacher.id, cid, "Бойко\nАрхипенко\nВовк\nГрицай")
    boyko = next(s for s in svc.list_students(teacher.id, cid) if s.full_name == "Бойко")
    arkh = next(s for s in svc.list_students(teacher.id, cid) if s.full_name == "Архипенко")
    svc.set_student_archived(teacher.id, boyko.id, True)
    svc.set_student_archived(teacher.id, arkh.id, True)
    infos = svc.list_students(teacher.id, cid)
    assert [s.archived for s in infos] == [False, False, True, True]
    assert [s.full_name for s in infos[:2]] == ["Вовк", "Грицай"]
    assert [s.position for s in infos] == [1, 2, 0, 0]


# ---------- add_student ----------


def test_add_student_duplicate(svc, teacher, klass):
    svc.add_student(teacher.id, klass.id, "Іваненко Петро")
    with pytest.raises(ClassError, match="Такий учень уже є в цьому класі"):
        svc.add_student(teacher.id, klass.id, "іваненко  петро")


def test_add_student_duplicate_of_archived(svc, teacher, klass):
    student = svc.add_student(teacher.id, klass.id, "Іваненко Петро")
    svc.set_student_archived(teacher.id, student.id, True)
    with pytest.raises(ClassError, match="вибулий"):
        svc.add_student(teacher.id, klass.id, "Іваненко Петро")


# ---------- видалення учня ----------


def test_student_removal_mode_and_delete_without_records(svc, teacher, klass, session):
    student = svc.add_student(teacher.id, klass.id, "Іваненко")
    assert svc.student_removal_mode(teacher.id, student.id) == "delete"
    svc.delete_student(teacher.id, student.id)
    assert count_students(session, klass.id) == 0


def test_student_with_lesson_entry_archive_only(svc, teacher, klass, session):
    student = svc.add_student(teacher.id, klass.id, "Іваненко")
    add_record_entry(session, session.get(Student, student.id), klass.id)
    assert svc.student_removal_mode(teacher.id, student.id) == "archive"
    with pytest.raises(ClassError):
        svc.delete_student(teacher.id, student.id)
    assert count_students(session, klass.id) == 1
    svc.set_student_archived(teacher.id, student.id, True)
    assert svc.list_students(teacher.id, klass.id)[0].archived is True


def test_student_with_final_grade_archive_only(svc, teacher, klass, session):
    student = svc.add_student(teacher.id, klass.id, "Іваненко")
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = Journal(class_id=klass.id, subject=subject)
    session.add(journal)
    session.flush()
    session.add(
        FinalGrade(journal=journal, student_id=student.id, kind=FinalGradeKind.SEMESTER_1, grade=9)
    )
    session.flush()
    assert svc.student_removal_mode(teacher.id, student.id) == "archive"
    with pytest.raises(ClassError):
        svc.delete_student(teacher.id, student.id)


# ---------- видалення класу ----------


def test_class_removal_with_journal(svc, teacher, klass, session):
    session.add(
        Journal(
            class_id=klass.id,
            subject=session.scalars(select(Subject).where(Subject.name == "Математика")).one(),
        )
    )
    session.flush()
    assert svc.class_removal_mode(teacher.id, klass.id) == "archive"
    with pytest.raises(ClassError):
        svc.delete_class(teacher.id, klass.id)
    assert session.get(SchoolClass, klass.id) is not None


def test_class_removal_without_journal(svc, teacher, klass, session):
    svc.add_student(teacher.id, klass.id, "Іваненко")
    assert svc.class_removal_mode(teacher.id, klass.id) == "delete"
    svc.delete_class(teacher.id, klass.id)
    session.expire_all()
    assert session.get(SchoolClass, klass.id) is None
    assert count_students(session, klass.id) == 0
    assert svc.list_classes(teacher.id, include_archived=True) == []


# ---------- архівований клас ----------


def test_archived_class_is_read_only(svc, teacher, klass):
    student = svc.add_student(teacher.id, klass.id, "Іваненко")
    svc.set_class_archived(teacher.id, klass.id, True)
    with pytest.raises(ClassError, match="архів"):
        svc.add_student(teacher.id, klass.id, "Петренко")
    with pytest.raises(ClassError, match="архів"):
        svc.import_students(teacher.id, klass.id, "Петренко")
    with pytest.raises(ClassError, match="архів"):
        svc.rename_student(teacher.id, student.id, "Петренко")
    with pytest.raises(ClassError, match="архів"):
        svc.update_class(teacher.id, klass.id, "9-Б", YEAR)


def test_restored_class_accepts_students(svc, teacher, klass):
    svc.set_class_archived(teacher.id, klass.id, True)
    svc.set_class_archived(teacher.id, klass.id, False)
    assert svc.add_student(teacher.id, klass.id, "Петренко").position == 1

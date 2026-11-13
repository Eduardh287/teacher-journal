"""Тести етапу 6 у JournalService: тематичні/семестрові/річні, «Зошит», нумерація, д/з, стовпчики."""
from datetime import date

import pytest
from sqlalchemy import select

from journal.models import ExtraColumn, ExtraGrade, FinalGrade, FinalGradeKind, Journal, Subject, Teacher
from journal.services.class_service import ClassError, ClassService
from journal.services.journal_service import JournalService
from journal.services.journal_types import JournalError, JournalNotFound, LessonNotFound, SemesterConflict
from journal.services.semesters import SemesterBoundaries
from journal.services.settings_service import SettingsService

YEAR = "2026-2027"
D = [date(2026, 9, day) for day in (1, 2, 3, 4, 5)]  # I семестр
S2 = [date(2027, 1, 11), date(2027, 1, 12), date(2027, 2, 1)]  # II семестр


class Ctx:
    """Короткі виклики сервісу для тестів (викладач, журнал, учні)."""

    def __init__(self, svc, teacher, journal, students):
        self.svc, self.t, self.j, self.students = svc, teacher, journal, students
        self.s = students[0]

    def lesson(self, d, kind="regular", **kw):
        return self.svc.create_lesson(self.t.id, self.j.id, d, kind, **kw)

    def grade(self, lesson, value, student=None, attendance="present"):
        self.svc.set_cell(self.t.id, lesson.id, student or self.s, attendance, value, None)

    def column(self, kind, lesson):
        return self.svc.create_column(self.t.id, self.j.id, kind, lesson.id)

    def cells(self, student=None):
        return self.svc.student_computed(self.t.id, self.j.id, student or self.s)

    def override(self, key, grade=None, na=False, student=None):
        return self.svc.set_override(self.t.id, self.j.id, student or self.s, key, grade, na)


@pytest.fixture
def teacher(session):
    t = Teacher(username="pytest_gr", password_hash="x", full_name="Т")
    session.add(t)
    session.flush()
    return t


@pytest.fixture
def svc(session):
    return JournalService(session)


@pytest.fixture
def classes(session):
    return ClassService(session)


@pytest.fixture
def ctx(session, svc, classes, teacher):
    c = classes.create_class(teacher.id, "9-А", YEAR)
    classes.add_student(teacher.id, c.id, "Андрієнко Іван")
    classes.add_student(teacher.id, c.id, "Бондаренко Олена")
    subject = session.scalars(select(Subject).where(Subject.name == "Математика")).one()
    journal = svc.create_journal(teacher.id, c.id, subject.id)
    return Ctx(svc, teacher, journal, [s.id for s in classes.list_students(teacher.id, c.id)])


# ---------- тематична ----------


def test_thematic_is_half_up_mean_of_period(ctx):
    l1, l2 = ctx.lesson(D[0]), ctx.lesson(D[1])
    ctx.grade(l1, 7)
    ctx.grade(l2, 8)
    col = ctx.column("thematic", l2)
    cell = ctx.cells()[("thematic", col.id)]
    assert (cell.auto, cell.auto_na, cell.total, cell.count) == (8, False, 15, 2)  # 7,5 → 8
    assert cell.value == 8 and not cell.is_manual and not cell.is_na


def test_thematic_period_starts_after_previous_thematic(ctx):
    l1, l2, l3 = ctx.lesson(D[0]), ctx.lesson(D[1]), ctx.lesson(D[2])
    for lesson, g in ((l1, 4), (l2, 6), (l3, 12)):
        ctx.grade(lesson, g)
    t1, t2 = ctx.column("thematic", l2), ctx.column("thematic", l3)
    cells = ctx.cells()
    assert cells[("thematic", t1.id)].auto == 5  # (4+6)/2
    assert cells[("thematic", t2.id)].auto == 12  # лише урок після першої тематичної


def test_grades_after_last_thematic_affect_nothing(ctx):
    l1, l2 = ctx.lesson(D[0]), ctx.lesson(D[1])
    ctx.grade(l1, 5)
    ctx.grade(l2, 12)
    t = ctx.column("thematic", l1)
    assert ctx.cells()[("thematic", t.id)].auto == 5


def test_thematic_period_is_limited_to_its_semester(ctx):
    a, b = ctx.lesson(D[0]), ctx.lesson(S2[0])
    ctx.grade(a, 4)
    ctx.grade(b, 10)
    t2 = ctx.column("thematic", b)
    assert ctx.cells()[("thematic", t2.id)].auto == 10  # оцінки I семестру не потрапляють


def test_thematic_without_grades_is_na(ctx):
    t = ctx.column("thematic", ctx.lesson(D[0]))
    cell = ctx.cells()[("thematic", t.id)]
    assert (cell.auto, cell.auto_na, cell.is_na, cell.value) == (None, True, True, None)


def test_only_counted_entries_are_grades(ctx):
    """Н/хв/з і коментарі без оцінки не рахуються; запізнення з оцінкою — рахується."""
    l1, l2, l3, l4 = (ctx.lesson(d) for d in D[:4])
    ctx.grade(l1, 10, attendance="late")
    ctx.grade(l2, None, attendance="absent")
    ctx.grade(l3, None, attendance="sick")
    ctx.svc.set_cell(ctx.t.id, l4.id, ctx.s, "present", None, "коментар")
    t = ctx.column("thematic", l4)
    cell = ctx.cells()[("thematic", t.id)]
    assert (cell.auto, cell.count) == (10, 1)


def test_all_dated_lesson_types_count_equally(ctx):
    kinds = ("regular", "test", "lab", "independent", "quiz")
    for d, kind in zip(D, kinds):
        ctx.grade(ctx.lesson(d, kind), 6)
    ctx.grade(ctx.lesson(date(2026, 9, 8), "project"), 12)
    t = ctx.column("thematic", ctx.lesson(date(2026, 9, 9)))
    cell = ctx.cells()[("thematic", t.id)]
    assert (cell.count, cell.total, cell.auto) == (6, 42, 7)


# ---------- семестрова й річна ----------


def test_semester_with_na_thematic_counts_zero(ctx):
    """Тематичні н/а, 8, 10 → семестрова 6."""
    l1, l2, l3 = ctx.lesson(D[0]), ctx.lesson(D[1]), ctx.lesson(D[2])
    ctx.grade(l2, 8)
    ctx.grade(l3, 10)
    for lesson in (l1, l2, l3):
        ctx.column("thematic", lesson)
    sem = ctx.cells()[("semester", 1)]
    assert (sem.auto, sem.total, sem.count) == (6, 18, 3)


def test_semester_without_thematics_is_na(ctx):
    ctx.grade(ctx.lesson(D[0]), 9)
    sem = ctx.cells()[("semester", 1)]
    assert sem.is_na and sem.auto is None
    assert ctx.cells()[("semester", 2)].is_na


def test_semester_all_thematics_na_stays_na(ctx):
    ctx.column("thematic", ctx.lesson(D[0]))
    sem = ctx.cells()[("semester", 1)]
    assert sem.auto_na and sem.count == 1


def _two_semester_journal(ctx, grade1, grade2):
    """Одна тематична на семестр: s1 = grade1, s2 = grade2 (None — без оцінок, тобто н/а)."""
    a, b = ctx.lesson(D[0]), ctx.lesson(S2[0])
    if grade1 is not None:
        ctx.grade(a, grade1)
    if grade2 is not None:
        ctx.grade(b, grade2)
    ctx.column("thematic", a)
    ctx.column("thematic", b)


@pytest.mark.parametrize(
    "g1, g2, expected",
    [(8, 10, 9), (8, None, 4), (9, None, 5), (None, 9, 5), (None, None, None)],
)
def test_annual_rules(ctx, g1, g2, expected):
    _two_semester_journal(ctx, g1, g2)
    annual = ctx.cells()[("annual", 0)]
    assert annual.value == expected
    assert annual.is_na == (expected is None)


def test_annual_with_semester_without_columns(ctx):
    ctx.column("thematic", ctx.lesson(D[0]))
    ctx.override(("semester", 1), 8)
    assert ctx.cells()[("annual", 0)].value == 4  # семестр II без тематичних = н/а = 0


def test_override_beats_auto_and_can_be_cleared(session, ctx):
    l1 = ctx.lesson(D[0])
    ctx.grade(l1, 7)
    t = ctx.column("thematic", l1)
    cells = ctx.override(("thematic", t.id), 11)
    cell = cells[("thematic", t.id)]
    assert (cell.auto, cell.override, cell.value, cell.is_manual) == (7, 11, 11, True)
    assert cells[("semester", 1)].auto == 11  # семестрова бере ефективне значення
    cells = ctx.override(("thematic", t.id), None)
    assert cells[("thematic", t.id)].value == 7 and not cells[("thematic", t.id)].is_manual
    assert session.scalars(select(ExtraGrade)).all() == []


def test_manual_na_on_thematic_counts_zero(ctx):
    l1, l2 = ctx.lesson(D[0]), ctx.lesson(D[1])
    ctx.grade(l1, 8)
    ctx.grade(l2, 10)
    t1, t2 = ctx.column("thematic", l1), ctx.column("thematic", l2)
    cells = ctx.override(("thematic", t1.id), na=True)
    first = cells[("thematic", t1.id)]
    assert first.is_na and first.value is None and first.is_manual and first.auto == 8
    assert cells[("semester", 1)].auto == 5  # (0 + 10) / 2
    assert t2


def test_manual_na_on_semester_and_annual(ctx):
    _two_semester_journal(ctx, 8, 10)
    cells = ctx.override(("semester", 2), na=True)
    assert cells[("semester", 2)].is_na and cells[("annual", 0)].value == 4
    cells = ctx.override(("annual", 0), na=True)
    assert cells[("annual", 0)].is_na and cells[("annual", 0)].auto == 4
    cells = ctx.override(("annual", 0), 12)
    assert cells[("annual", 0)].value == 12
    row = ctx.svc.repo.get_final_grade(ctx.j.id, ctx.s, FinalGradeKind.ANNUAL)
    assert (row.grade, row.is_na) == (12, False)


def test_override_validation(ctx):
    t = ctx.column("thematic", ctx.lesson(D[0]))
    for bad in (0, 13, True):
        with pytest.raises(JournalError, match="від 1 до 12"):
            ctx.override(("thematic", t.id), bad)
    with pytest.raises(JournalError):
        ctx.override(("thematic", t.id), 5, na=True)
    with pytest.raises(JournalError):
        ctx.override(("semester", 3), 5)
    with pytest.raises(JournalError):
        ctx.override(("thematic", 999999), 5)
    with pytest.raises(JournalError):
        ctx.override(("notebook", t.id), 5)  # вид не збігається


def test_override_on_withdrawn_student_refused(ctx, classes, teacher):
    t = ctx.column("thematic", ctx.lesson(D[0]))
    classes.set_student_archived(teacher.id, ctx.s, True)
    with pytest.raises(JournalError, match="вибув"):
        ctx.override(("thematic", t.id), 5)


# ---------- «Зошит» ----------


def test_notebook_grades_count_nowhere_and_are_no_boundary(ctx):
    l1, l2, l3 = ctx.lesson(D[0]), ctx.lesson(D[1]), ctx.lesson(D[2])
    ctx.grade(l1, 6)
    ctx.grade(l2, 8)
    ctx.grade(l3, 10)
    nb = ctx.column("notebook", l2)
    cell = ctx.override(("notebook", nb.id), 12)[("notebook", nb.id)]
    assert (cell.override, cell.value) == (12, 12)
    t = ctx.column("thematic", l3)
    cells = ctx.cells()
    assert cells[("thematic", t.id)].auto == 8  # (6+8+10)/3: «Зошит» не рахується й не розриває період
    assert cells[("semester", 1)].auto == 8


def test_notebook_has_no_na_and_can_be_cleared(ctx):
    nb = ctx.column("notebook", ctx.lesson(D[0]))
    with pytest.raises(JournalError, match="н/а"):
        ctx.override(("notebook", nb.id), na=True)
    ctx.override(("notebook", nb.id), 9)
    assert ctx.cells()[("notebook", nb.id)].value == 9
    ctx.override(("notebook", nb.id), None)
    assert ctx.cells()[("notebook", nb.id)].value is None


def test_delete_notebook_with_grades_refused_until_cleared(ctx):
    nb = ctx.column("notebook", ctx.lesson(D[0]))
    ctx.override(("notebook", nb.id), 9)
    ctx.override(("notebook", nb.id), 5, student=ctx.students[1])
    with pytest.raises(JournalError) as error:
        ctx.svc.delete_column(ctx.t.id, nb.id)
    assert str(error.value) == "У стовпчику «Зошит» є оцінки (2) — його не можна видалити. Спершу очистьте їх."
    ctx.override(("notebook", nb.id), None)
    ctx.override(("notebook", nb.id), None, student=ctx.students[1])
    ctx.svc.delete_column(ctx.t.id, nb.id)
    assert ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1).extra_columns == []


def test_delete_thematic_removes_overrides(session, ctx):
    t = ctx.column("thematic", ctx.lesson(D[0]))
    ctx.override(("thematic", t.id), 7)
    ctx.svc.delete_column(ctx.t.id, t.id)
    assert session.scalars(select(ExtraGrade)).all() == []
    assert session.scalars(select(ExtraColumn)).all() == []


# ---------- стовпчики: створення, порядок, переміщення ----------


def test_create_column_rules(ctx):
    l1, l2 = ctx.lesson(D[0]), ctx.lesson(D[1])
    t = ctx.column("thematic", l1)
    assert (t.kind, t.semester, t.after_date, t.ordinal, t.grade_count) == ("thematic", 1, D[0], 1, 0)
    with pytest.raises(JournalError, match="Після цього уроку вже є такий стовпчик"):
        ctx.column("thematic", l1)
    ctx.column("notebook", l1)  # інший вид на ту саму дату можна
    assert ctx.column("thematic", l2).ordinal == 2
    with pytest.raises(JournalError):
        ctx.svc.create_column(ctx.t.id, ctx.j.id, "semester", l1.id)


def test_same_day_lessons_have_separate_anchors(ctx):
    a, b = ctx.lesson(D[0]), ctx.lesson(D[0])
    ctx.column("thematic", a)
    ctx.column("thematic", b)  # якір - конкретний урок, а не дата
    with pytest.raises(JournalError, match="вже є такий стовпчик"):
        ctx.column("thematic", b)


def test_grid_column_order_and_keys(ctx):
    l1, l2, l3 = ctx.lesson(D[0]), ctx.lesson(D[1]), ctx.lesson(D[2])
    t = ctx.column("thematic", l2)
    nb = ctx.column("notebook", l2)
    grid = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1)
    assert [(c.kind, c.id) for c in grid.columns] == [
        ("lesson", l1.id), ("lesson", l2.id), ("thematic", t.id), ("notebook", nb.id),
        ("lesson", l3.id), ("semester", None),
    ]
    assert {(x.kind, x.ordinal) for x in grid.extra_columns} == {("thematic", 1), ("notebook", 1)}
    assert {key for (_, key) in grid.computed} == {("thematic", t.id), ("notebook", nb.id), ("semester", 1)}
    assert {sid for (sid, _) in grid.computed} == set(ctx.students)
    grid2 = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 2)
    assert [(c.kind, c.id) for c in grid2.columns] == [("semester", None), ("annual", None)]
    assert {key for (_, key) in grid2.computed} == {("semester", 2), ("annual", 0)}


def test_move_column(ctx):
    l1, l2, l3 = ctx.lesson(D[0]), ctx.lesson(D[1]), ctx.lesson(D[2])
    ctx.grade(l1, 4)
    ctx.grade(l2, 8)
    ctx.grade(l3, 12)
    t = ctx.column("thematic", l1)
    other = ctx.column("thematic", l2)
    with pytest.raises(JournalError, match="вже є такий стовпчик"):
        ctx.svc.move_column(ctx.t.id, t.id, l2.id)
    moved = ctx.svc.move_column(ctx.t.id, t.id, l3.id)
    assert (moved.after_date, moved.ordinal) == (D[2], 2)
    assert ctx.cells()[("thematic", other.id)].auto == 6  # (4+8)/2: період тепер від початку семестру
    ctx.svc.move_column(ctx.t.id, t.id, l3.id)  # на те саме місце — без помилки


def test_move_column_to_other_semester(ctx):
    l1, l2 = ctx.lesson(D[0]), ctx.lesson(S2[0])
    t = ctx.column("thematic", l1)
    moved = ctx.svc.move_column(ctx.t.id, t.id, l2.id)
    assert moved.semester == 2 and moved.ordinal == 1


def test_columns_check_ownership(session, svc, ctx):
    other = Teacher(username="pytest_gr2", password_hash="x", full_name="О")
    session.add(other)
    session.flush()
    l1 = ctx.lesson(D[0])
    t = ctx.column("thematic", l1)
    with pytest.raises(JournalNotFound):
        svc.create_column(other.id, ctx.j.id, "thematic", l1.id)
    with pytest.raises(JournalError):
        svc.delete_column(other.id, t.id)
    with pytest.raises(JournalError):
        svc.move_column(other.id, t.id, l1.id)
    with pytest.raises(JournalNotFound):
        svc.set_override(other.id, ctx.j.id, ctx.s, ("thematic", t.id), 5)
    with pytest.raises(JournalNotFound):
        svc.student_computed(other.id, ctx.j.id, ctx.s)
    with pytest.raises(LessonNotFound):
        svc.set_homework(other.id, l1.id, "x")


# ---------- нумерація, домашнє завдання ----------


def test_numbering_is_continuous_across_semesters_and_ignores_columns(ctx):
    late = ctx.lesson(S2[0])
    first = ctx.lesson(D[0])
    second = ctx.lesson(D[1])
    ctx.column("thematic", first)
    ctx.column("notebook", second)
    g1 = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1)
    g2 = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 2)
    assert [(x.id, x.number) for x in g1.lessons] == [(first.id, 1), (second.id, 2)]
    assert [(x.id, x.number) for x in g2.lessons] == [(late.id, 3)]
    assert ctx.lesson(D[2]).number == 3
    assert ctx.svc.get_grid(ctx.t.id, ctx.j.id, 2).lessons[0].number == 4


def test_homework_create_update_and_quick_edit(ctx):
    lesson = ctx.lesson(D[0], homework="  §5, №3  ")
    assert lesson.homework == "§5, №3"
    assert ctx.lesson(D[1]).homework is None
    updated = ctx.svc.update_lesson(ctx.t.id, lesson.id, D[0], "quiz", "Тема", "§6")
    assert (updated.homework, updated.lesson_type) == ("§6", "quiz")
    assert ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1).lessons[0].homework == "§6"
    assert ctx.svc.set_homework(ctx.t.id, lesson.id, "   ").homework is None
    assert ctx.svc.set_homework(ctx.t.id, lesson.id, "а" * 500).homework == "а" * 500
    with pytest.raises(JournalError, match="не довше 500"):
        ctx.svc.set_homework(ctx.t.id, lesson.id, "а" * 501)
    with pytest.raises(JournalError):
        ctx.lesson(D[2], homework="а" * 501)


def test_quiz_and_project_types_roundtrip(ctx):
    assert ctx.lesson(D[0], "quiz").lesson_type == "quiz"
    assert ctx.lesson(D[1], "project").lesson_type == "project"
    with pytest.raises(JournalError, match="Невідомий тип уроку"):
        ctx.lesson(D[2], "exam")


# ---------- межі, видалення журналу, учні ----------


def test_boundary_change_recomputes_column_semester(session, ctx, teacher):
    t = ctx.column("thematic", ctx.lesson(date(2026, 12, 20)))
    assert t.semester == 1
    SettingsService(session).set_semesters(teacher.id, SemesterBoundaries(9, 11, 12, 6))
    assert session.get(ExtraColumn, t.id).semester == 2


def test_boundary_change_conflicts_on_column_in_vacation(session, ctx, teacher):
    l1 = ctx.lesson(D[0])
    ctx.column("thematic", l1)
    ctx.svc.delete_lesson(ctx.t.id, l1.id)  # якір зник, стовпчик лишився на 1 вересня
    with pytest.raises(SemesterConflict):
        SettingsService(session).set_semesters(teacher.id, SemesterBoundaries(10, 12, 1, 6))


def test_journal_with_only_extra_column_needs_contents_flag(ctx):
    l1 = ctx.lesson(D[0])
    t = ctx.column("thematic", l1)
    ctx.override(("thematic", t.id), 7)
    ctx.svc.delete_lesson(ctx.t.id, l1.id)
    with pytest.raises(JournalError, match="У журналі є уроки чи оцінки"):
        ctx.svc.delete_journal(ctx.t.id, ctx.j.id)


def test_delete_journal_with_contents_removes_extra_columns(session, ctx):
    l1 = ctx.lesson(D[0])
    ctx.grade(l1, 5)
    t = ctx.column("thematic", l1)
    nb = ctx.column("notebook", l1)
    ctx.override(("thematic", t.id), 7)
    ctx.override(("notebook", nb.id), 9)
    ctx.override(("semester", 1), 6)
    ctx.svc.delete_journal(ctx.t.id, ctx.j.id, with_contents=True)
    assert session.get(Journal, ctx.j.id) is None
    assert session.scalars(select(ExtraColumn)).all() == []
    assert session.scalars(select(ExtraGrade)).all() == []
    assert session.scalars(select(FinalGrade)).all() == []


def test_student_with_extra_grade_cannot_be_deleted(ctx, classes, teacher):
    nb = ctx.column("notebook", ctx.lesson(D[0]))
    ctx.override(("notebook", nb.id), 9)
    assert classes.student_removal_mode(teacher.id, ctx.s) == "archive"
    with pytest.raises(ClassError, match="лише позначити як вибулого"):
        classes.delete_student(teacher.id, ctx.s)
    assert classes.student_removal_mode(teacher.id, ctx.students[1]) == "delete"


def test_withdrawn_student_with_only_extra_grade_stays_listed(ctx, classes, teacher):
    nb = ctx.column("notebook", ctx.lesson(D[0]))
    ctx.override(("notebook", nb.id), 9)
    classes.set_student_archived(teacher.id, ctx.s, True)
    grid = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1)
    assert [(s.id, s.archived) for s in grid.students] == [(ctx.students[1], False), (ctx.s, True)]
    assert grid.computed[(ctx.s, ("notebook", nb.id))].value == 9
    assert ctx.cells()[("semester", 1)].is_na  # обчислення працюють і для вибулого
    classes.set_student_archived(teacher.id, ctx.students[1], True)
    assert [s.id for s in ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1).students] == [ctx.s]


def test_subject_pp_tfv_present_once(session):
    names = [s.name for s in session.scalars(select(Subject)).all()]
    assert names.count("ПП ТФВ") == 1


# ---------- порядок стовпчиків: стоять там, де їх додали ----------


def _order(ctx, semester=1):
    grid = ctx.svc.get_grid(ctx.t.id, ctx.j.id, semester)
    names = {("lesson", x.id): f"У{i}" for i, x in enumerate(ctx.made, start=1)}
    names.update({("thematic", x.id): "Тем" for x in grid.extra_columns if x.kind == "thematic"})
    names.update({("notebook", x.id): "Зош" for x in grid.extra_columns if x.kind == "notebook"})
    names.update({("semester", None): "Сем", ("annual", None): "Рік"})
    return " | ".join(names[(c.kind, c.id)] for c in grid.columns)


@pytest.fixture
def lessons_made(ctx):
    """Створює уроки й пам'ятає їх у ctx.made (мітки «У1…» у _order — за порядком у цьому списку)."""
    ctx.made = []

    def make(d):
        lesson = ctx.lesson(d)
        ctx.made.append(lesson)
        return lesson

    return make


def test_columns_stay_where_added_even_with_later_same_day_lessons(ctx, lessons_made):
    lessons_made(date(2026, 11, 13))
    l2 = lessons_made(date(2026, 11, 13))
    ctx.column("thematic", l2)
    ctx.column("notebook", l2)
    lessons_made(date(2026, 11, 13))
    lessons_made(date(2026, 11, 14))
    assert _order(ctx) == "У1 | У2 | Тем | Зош | У3 | У4 | Сем"


def test_same_day_lesson_after_thematic_feeds_next_period(ctx, lessons_made):
    l1, l2 = lessons_made(D[0]), lessons_made(D[0])
    ctx.grade(l1, 6)
    ctx.grade(l2, 8)
    t1 = ctx.column("thematic", l2)
    l3 = lessons_made(D[0])
    ctx.grade(l3, 12)
    l4 = lessons_made(D[1])
    t2 = ctx.column("thematic", l4)
    cells = ctx.cells()
    assert cells[("thematic", t1.id)].auto == 7  # (6+8)/2, без У3
    assert cells[("thematic", t2.id)].auto == 12  # У3 (того ж дня, але пізніше) → наступний період


def test_two_columns_after_one_lesson_keep_creation_order(ctx, lessons_made):
    l1 = lessons_made(D[0])
    nb = ctx.column("notebook", l1)
    t = ctx.column("thematic", l1)
    lessons_made(D[1])
    grid = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1)
    assert [(c.kind, c.id) for c in grid.columns][:3] == [("lesson", l1.id), ("notebook", nb.id), ("thematic", t.id)]


def test_backdated_lesson_sorts_by_date_before_column(ctx, lessons_made):
    lessons_made(D[1])
    l2 = lessons_made(D[2])
    ctx.column("thematic", l2)
    lessons_made(D[0])  # створений пізніше, але датований раніше
    ctx.made.sort(key=lambda x: x.lesson_date)
    assert _order(ctx) == "У1 | У2 | У3 | Тем | Сем"


def test_move_column_reanchors(ctx, lessons_made):
    l1, l2 = lessons_made(D[0]), lessons_made(D[1])
    lessons_made(D[2])
    t = ctx.column("thematic", l1)
    assert _order(ctx) == "У1 | Тем | У2 | У3 | Сем"
    ctx.svc.move_column(ctx.t.id, t.id, l2.id)
    assert _order(ctx) == "У1 | У2 | Тем | У3 | Сем"
    assert ctx.svc.repo.get_extra_column(t.id).after_lesson_id == l2.id


def test_delete_anchor_lesson_keeps_column_after_previous(ctx, lessons_made, session):
    l1, l2 = lessons_made(D[0]), lessons_made(D[1])
    lessons_made(D[2])
    t = ctx.column("thematic", l2)
    ctx.svc.delete_lesson(ctx.t.id, l2.id)
    ctx.made.remove(l2)
    assert _order(ctx) == "У1 | Тем | У2 | Сем"
    assert session.get(ExtraColumn, t.id).after_lesson_id == l1.id


def test_delete_first_anchor_lesson_column_goes_to_start_of_its_date(ctx, lessons_made, session):
    l1 = lessons_made(D[0])
    lessons_made(D[1])
    t = ctx.column("notebook", l1)
    ctx.svc.delete_lesson(ctx.t.id, l1.id)
    ctx.made.remove(l1)
    assert _order(ctx) == "Зош | У1 | Сем"
    col = session.get(ExtraColumn, t.id)
    assert (col.after_lesson_id, col.after_date) == (None, D[0])


def test_delete_anchor_lesson_with_duplicate_on_previous_drops_empty_column(ctx, lessons_made, session):
    l1, l2 = lessons_made(D[0]), lessons_made(D[1])
    ctx.column("thematic", l1)
    t2 = ctx.column("thematic", l2)
    ctx.svc.delete_lesson(ctx.t.id, l2.id)
    assert session.get(ExtraColumn, t2.id) is None


def test_delete_anchor_lesson_blocked_when_duplicate_has_grades(ctx, lessons_made):
    l1, l2 = lessons_made(D[0]), lessons_made(D[1])
    ctx.column("thematic", l1)
    t2 = ctx.column("thematic", l2)
    ctx.override(("thematic", t2.id), 9)
    with pytest.raises(JournalError, match="вже є такий стовпчик"):
        ctx.svc.delete_lesson(ctx.t.id, l2.id)


def test_changing_anchor_lesson_date_moves_column(ctx, lessons_made, session):
    l1, l2 = lessons_made(D[0]), lessons_made(D[2])
    t = ctx.column("thematic", l1)
    ctx.svc.update_lesson(ctx.t.id, l1.id, D[3], "regular", None)
    grid = ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1)
    assert [(c.kind, c.id) for c in grid.columns] == [
        ("lesson", l2.id), ("lesson", l1.id), ("thematic", t.id), ("semester", None)
    ]
    assert session.get(ExtraColumn, t.id).after_date == D[3]


def test_changing_anchor_lesson_date_to_other_semester_moves_column(ctx, lessons_made, session):
    l1 = lessons_made(D[0])
    t = ctx.column("thematic", l1)
    ctx.svc.update_lesson(ctx.t.id, l1.id, S2[0], "regular", None)
    assert session.get(ExtraColumn, t.id).semester == 2
    assert [x.id for x in ctx.svc.get_grid(ctx.t.id, ctx.j.id, 2).extra_columns] == [t.id]
    assert ctx.svc.get_grid(ctx.t.id, ctx.j.id, 1).extra_columns == []
    with pytest.raises(JournalError):  # канікули: така сама перевірка, як для уроку
        ctx.svc.update_lesson(ctx.t.id, l1.id, date(2026, 7, 10), "regular", None)


def test_migration_backfills_anchor_lesson(session, ctx):
    import importlib.util

    from sqlalchemy import text

    from journal.config import PROJECT_ROOT

    path = next((PROJECT_ROOT / "migrations" / "versions").glob("*a7c41d9e5b02*.py"))
    spec = importlib.util.spec_from_file_location("mig_a7c41d9e5b02", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    a, b = ctx.lesson(D[0]), ctx.lesson(D[0])
    col = ExtraColumn(journal_id=ctx.j.id, kind="thematic", semester=1, after_date=D[0])
    orphan = ExtraColumn(journal_id=ctx.j.id, kind="notebook", semester=1, after_date=D[3])  # уроків на дату немає
    session.add_all([col, orphan])
    session.flush()
    assert col.after_lesson_id is None
    session.execute(text(module.BACKFILL_SQL))
    session.refresh(col)
    session.refresh(orphan)
    assert col.after_lesson_id == max(a.id, b.id)  # останній урок цієї дати
    assert orphan.after_lesson_id is None


def test_delete_first_lesson_of_semester2_keeps_column_in_semester2(ctx, session):
    """Рецензія Fable (PR #16): стовпчик не «переїжджає» в І семестр і не змінює його оцінок."""
    from datetime import date

    l1 = ctx.svc.create_lesson(ctx.t.id, ctx.j.id, date(2026, 12, 1))   # І семестр
    l2 = ctx.svc.create_lesson(ctx.t.id, ctx.j.id, date(2027, 1, 12))   # ІІ семестр
    t = ctx.svc.create_column(ctx.t.id, ctx.j.id, "thematic", l2.id)
    ctx.svc.set_override(ctx.t.id, ctx.j.id, ctx.s, ("thematic", t.id), 4)
    before = ctx.svc.student_computed(ctx.t.id, ctx.j.id, ctx.s)
    ctx.svc.delete_lesson(ctx.t.id, l2.id)
    column = session.get(ExtraColumn, t.id)
    assert column.semester == 2 and column.after_lesson_id is None
    after = ctx.svc.student_computed(ctx.t.id, ctx.j.id, ctx.s)
    assert after[("semester", 1)] == before[("semester", 1)]
    assert after[("semester", 2)].value == 4
    assert l1.id  # урок І семестру не зачеплено

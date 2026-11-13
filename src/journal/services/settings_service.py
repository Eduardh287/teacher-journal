"""Налаштування викладача: межі семестрів (етап 5.2, docs/specs/stage-5.2.md)."""
from sqlalchemy.orm import Session

from journal.models import Journal, Teacher
from journal.repositories.journal_repository import JournalRepository
from journal.services.boundaries_rows import boundaries_of, set_boundaries
from journal.services.journal_types import JournalError, LessonConflict, SemesterConflict
from journal.services.semesters import SemesterBoundaries
from journal.services.ua_sort import class_name_key, ukrainian_sort_key


def apply_boundaries(
    repo: JournalRepository, journals: list[Journal], boundaries: SemesterBoundaries
) -> int:
    """Застосовує межі до журналів: перевіряє всі уроки й extra-стовпчики, перераховує semester.

    Якщо хоч один урок потрапляє в канікули чи поза навчальний рік — нічого не змінює й
    кидає SemesterConflict (уроки впорядковані за роком, класом, предметом і датою).
    Повертає кількість оновлених журналів.
    """
    lessons = repo.lessons_of_journals([j.id for j in journals])
    by_journal = {j.id: j for j in journals}
    conflicts: list[LessonConflict] = []
    new_semesters: dict[int, int] = {}
    for lesson in lessons:
        journal = by_journal[lesson.journal_id]
        school_class = journal.school_class
        semester = boundaries.semester_of_month(lesson.lesson_date.month)
        if semester is None or not boundaries.contains(school_class.school_year, lesson.lesson_date):
            conflicts.append(
                LessonConflict(
                    journal.id,
                    school_class.name,
                    school_class.school_year,
                    journal.subject.name,
                    lesson.lesson_date,
                )
            )
        else:
            new_semesters[lesson.id] = semester
    # Extra-стовпчики (тематична, зошит) теж прив'язані до дати: їхній семестр перераховується.
    # after_date завжди дорівнює даті уроку-якоря (сервіс синхронізує її при створенні, перенесенні,
    # зміні дати й видаленні якоря), тож межі перевіряються за датою якоря.
    columns = repo.extra_columns_of_journals([j.id for j in journals])
    new_column_semesters: dict[int, int] = {}
    for column in columns:
        journal = by_journal[column.journal_id]
        school_class = journal.school_class
        semester = boundaries.semester_of_month(column.after_date.month)
        if semester is None or not boundaries.contains(school_class.school_year, column.after_date):
            conflicts.append(
                LessonConflict(
                    journal.id,
                    school_class.name,
                    school_class.school_year,
                    journal.subject.name,
                    column.after_date,
                )
            )
        else:
            new_column_semesters[column.id] = semester
    if conflicts:
        conflicts.sort(
            key=lambda c: (
                c.school_year,
                class_name_key(c.class_name),
                ukrainian_sort_key(c.subject_name),
                c.lesson_date,
            )
        )
        raise SemesterConflict(conflicts)
    for lesson in lessons:
        lesson.semester = new_semesters[lesson.id]
    for column in columns:
        column.semester = new_column_semesters[column.id]
    for journal in journals:
        set_boundaries(journal, boundaries)
    repo.session.flush()
    return len(journals)


class SettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = JournalRepository(session)

    def get_semesters(self, teacher_id: int) -> SemesterBoundaries:
        """Глобальні межі семестрів викладача."""
        return boundaries_of(self._teacher(teacher_id))

    def set_semesters(self, teacher_id: int, boundaries: SemesterBoundaries) -> int:
        """Зберігає межі й застосовує їх до всіх журналів класів НЕ в архіві
        (перераховує lessons.semester). Повертає кількість оновлених журналів.
        Помилки: SemesterError (неправильні межі), SemesterConflict (уроки в канікулах) —
        тоді нічого не зберігається."""
        boundaries.validate()
        teacher = self._teacher(teacher_id)
        journals = self.repo.journals_for_teacher(teacher_id, include_archived=False)
        updated = apply_boundaries(self.repo, journals, boundaries)
        set_boundaries(teacher, boundaries)
        self.session.flush()
        return updated

    def _teacher(self, teacher_id: int) -> Teacher:
        teacher = self.repo.get_teacher(teacher_id)
        if teacher is None:
            raise JournalError("Викладача не знайдено")
        return teacher

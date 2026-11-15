"""Налаштування викладача: межі семестрів (етап 5.2, docs/specs/stage-5.2.md)."""
from sqlalchemy.orm import Session

from journal.models import ExtraColumn, Journal, Lesson, Teacher
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
    by_journal = {j.id: j for j in journals}
    ids = list(by_journal)
    # Extra-стовпчики (тематична, зошит) теж прив'язані до дати: after_date завжди дорівнює даті
    # уроку-якоря (сервіс синхронізує її при створенні, перенесенні, зміні дати й видаленні якоря).
    dated = [(lesson, lesson.journal_id, lesson.lesson_date) for lesson in repo.lessons_of_journals(ids)]
    dated += [(column, column.journal_id, column.after_date) for column in repo.extra_columns_of_journals(ids)]
    conflicts: list[LessonConflict] = []
    new_semesters: list[tuple[Lesson | ExtraColumn, int]] = []
    for item, journal_id, day in dated:
        journal = by_journal[journal_id]
        school_class = journal.school_class
        semester = boundaries.semester_of_month(day.month)
        if semester is None or not boundaries.contains(school_class.school_year, day):
            conflicts.append(
                LessonConflict(journal.id, school_class.name, school_class.school_year, journal.subject.name, day)
            )
        else:
            new_semesters.append((item, semester))
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
    for item, semester in new_semesters:
        item.semester = semester
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

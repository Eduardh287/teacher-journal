"""Доступ до журналів, уроків і клітинок. Лише запити — без бізнес-правил."""
from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from journal.models import (
    FinalGrade,
    Journal,
    Lesson,
    LessonEntry,
    SchoolClass,
    Student,
    Subject,
)


class JournalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- журнали ---

    def journals_for_teacher(self, teacher_id: int, include_archived: bool) -> list[Journal]:
        query = (
            select(Journal)
            .join(SchoolClass, Journal.class_id == SchoolClass.id)
            .where(SchoolClass.teacher_id == teacher_id)
        )
        if not include_archived:
            query = query.where(SchoolClass.archived.is_(False))
        return list(self.session.scalars(query))

    def get_journal(self, journal_id: int) -> Journal | None:
        return self.session.get(Journal, journal_id)

    def get_class(self, class_id: int) -> SchoolClass | None:
        return self.session.get(SchoolClass, class_id)

    def lesson_counts(self, journal_ids: list[int]) -> dict[int, int]:
        if not journal_ids:
            return {}
        rows = self.session.execute(
            select(Lesson.journal_id, func.count())
            .where(Lesson.journal_id.in_(journal_ids))
            .group_by(Lesson.journal_id)
        )
        return {journal_id: count for journal_id, count in rows}

    def has_lessons_or_finals(self, journal_id: int) -> bool:
        has_lessons = exists().where(Lesson.journal_id == journal_id)
        has_finals = exists().where(FinalGrade.journal_id == journal_id)
        return bool(self.session.scalar(select(has_lessons | has_finals)))

    def candidate_classes(self, teacher_id: int) -> list[SchoolClass]:
        """Неархівні класи викладача."""
        return list(
            self.session.scalars(
                select(SchoolClass).where(
                    SchoolClass.teacher_id == teacher_id, SchoolClass.archived.is_(False)
                )
            )
        )

    def subjects(self) -> list[Subject]:
        return list(self.session.scalars(select(Subject)))

    def get_subject(self, subject_id: int) -> Subject | None:
        return self.session.get(Subject, subject_id)

    def journal_exists(self, class_id: int, subject_id: int) -> bool:
        return bool(
            self.session.scalar(
                select(exists().where(Journal.class_id == class_id, Journal.subject_id == subject_id))
            )
        )

    def existing_pairs(self, class_ids: list[int]) -> set[tuple[int, int]]:
        if not class_ids:
            return set()
        rows = self.session.execute(
            select(Journal.class_id, Journal.subject_id).where(Journal.class_id.in_(class_ids))
        )
        return {(c, s) for c, s in rows}

    # --- уроки ---

    def get_lesson(self, lesson_id: int) -> Lesson | None:
        return self.session.get(Lesson, lesson_id)

    def lessons(self, journal_id: int, semester: int) -> list[Lesson]:
        return list(
            self.session.scalars(
                select(Lesson)
                .where(Lesson.journal_id == journal_id, Lesson.semester == semester)
                .order_by(Lesson.lesson_date, Lesson.id)
            )
        )

    def entry_counts(self, lesson_ids: list[int]) -> dict[int, int]:
        if not lesson_ids:
            return {}
        rows = self.session.execute(
            select(LessonEntry.lesson_id, func.count())
            .where(LessonEntry.lesson_id.in_(lesson_ids))
            .group_by(LessonEntry.lesson_id)
        )
        return {lesson_id: count for lesson_id, count in rows}

    def entries(self, lesson_ids: list[int]) -> list[LessonEntry]:
        if not lesson_ids:
            return []
        return list(
            self.session.scalars(select(LessonEntry).where(LessonEntry.lesson_id.in_(lesson_ids)))
        )

    def entry_count(self, lesson_id: int) -> int:
        return self.session.scalar(
            select(func.count()).select_from(LessonEntry).where(LessonEntry.lesson_id == lesson_id)
        )

    def get_entry(self, lesson_id: int, student_id: int) -> LessonEntry | None:
        return self.session.get(LessonEntry, (lesson_id, student_id))

    # --- учні ---

    def get_student(self, student_id: int) -> Student | None:
        return self.session.get(Student, student_id)

    def students(self, class_id: int) -> list[Student]:
        return list(self.session.scalars(select(Student).where(Student.class_id == class_id)))

    def student_ids_with_entries(self, journal_id: int) -> set[int]:
        """Учні, які мають хоч одну клітинку в цьому журналі."""
        rows = self.session.scalars(
            select(LessonEntry.student_id)
            .join(Lesson, Lesson.id == LessonEntry.lesson_id)
            .where(Lesson.journal_id == journal_id)
            .distinct()
        )
        return set(rows)

    # --- запис ---

    def add(self, obj) -> None:
        self.session.add(obj)
        self.session.flush()

    def delete(self, obj) -> None:
        self.session.delete(obj)
        self.session.flush()

    def delete_journal_contents(self, journal_id: int) -> None:
        """Підсумкові оцінки й уроки журналу (відмітки уроків видаляє БД каскадом)."""
        self.session.execute(delete(FinalGrade).where(FinalGrade.journal_id == journal_id))
        self.session.execute(delete(Lesson).where(Lesson.journal_id == journal_id))
        self.session.flush()
        self.session.expire_all()

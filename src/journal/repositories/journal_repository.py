"""Доступ до журналів, уроків і клітинок. Лише запити — без бізнес-правил."""
from sqlalchemy import delete, exists, func, select, union
from sqlalchemy.orm import Session

from journal.models import (
    ExtraColumn,
    ExtraGrade,
    FinalGrade,
    Journal,
    Lesson,
    LessonEntry,
    SchoolClass,
    Student,
    Subject,
    Teacher,
)


class JournalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- журнали ---

    def get_teacher(self, teacher_id: int) -> Teacher | None:
        return self.session.get(Teacher, teacher_id)

    def journals_of_class(self, class_id: int) -> list[Journal]:
        return list(self.session.scalars(select(Journal).where(Journal.class_id == class_id)))

    def lessons_of_journals(self, journal_ids: list[int]) -> list[Lesson]:
        """Усі уроки журналів (для перевірки й перерахунку семестрів)."""
        if not journal_ids:
            return []
        return list(
            self.session.scalars(
                select(Lesson)
                .where(Lesson.journal_id.in_(journal_ids))
                .order_by(Lesson.lesson_date, Lesson.id)
            )
        )

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
        has_columns = exists().where(ExtraColumn.journal_id == journal_id)
        return bool(self.session.scalar(select(has_lessons | has_finals | has_columns)))

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
        """Учні, які мають у цьому журналі клітинку, оцінку extra-стовпчика чи ручну підсумкову."""
        rows = self.session.scalars(
            union(
                select(LessonEntry.student_id)
                .join(Lesson, Lesson.id == LessonEntry.lesson_id)
                .where(Lesson.journal_id == journal_id),
                select(ExtraGrade.student_id)
                .join(ExtraColumn, ExtraColumn.id == ExtraGrade.column_id)
                .where(ExtraColumn.journal_id == journal_id),
                select(FinalGrade.student_id).where(FinalGrade.journal_id == journal_id),
            )
        )
        return set(rows)

    # --- стовпчики без дати, підсумкові оцінки (етап 6) ---

    def all_lessons(self, journal_id: int) -> list[Lesson]:
        """Усі уроки журналу за (дата, id) — основа наскрізної нумерації й обчислень."""
        return list(
            self.session.scalars(
                select(Lesson).where(Lesson.journal_id == journal_id).order_by(Lesson.lesson_date, Lesson.id)
            )
        )

    def extra_columns(self, journal_id: int) -> list[ExtraColumn]:
        return list(
            self.session.scalars(
                select(ExtraColumn)
                .where(ExtraColumn.journal_id == journal_id)
                .order_by(ExtraColumn.after_date, ExtraColumn.id)
            )
        )

    def extra_columns_of_journals(self, journal_ids: list[int]) -> list[ExtraColumn]:
        if not journal_ids:
            return []
        return list(
            self.session.scalars(select(ExtraColumn).where(ExtraColumn.journal_id.in_(journal_ids)))
        )

    def get_extra_column(self, column_id: int) -> ExtraColumn | None:
        return self.session.get(ExtraColumn, column_id)

    def find_extra_column(self, journal_id: int, kind, after_date) -> ExtraColumn | None:
        return self.session.scalar(
            select(ExtraColumn).where(
                ExtraColumn.journal_id == journal_id,
                ExtraColumn.kind == kind,
                ExtraColumn.after_date == after_date,
            )
        )

    def extra_grades(self, journal_id: int) -> list[ExtraGrade]:
        return list(
            self.session.scalars(
                select(ExtraGrade)
                .join(ExtraColumn, ExtraColumn.id == ExtraGrade.column_id)
                .where(ExtraColumn.journal_id == journal_id)
            )
        )

    def extra_grade_counts(self, journal_id: int) -> dict[int, int]:
        rows = self.session.execute(
            select(ExtraGrade.column_id, func.count())
            .join(ExtraColumn, ExtraColumn.id == ExtraGrade.column_id)
            .where(ExtraColumn.journal_id == journal_id)
            .group_by(ExtraGrade.column_id)
        )
        return {column_id: count for column_id, count in rows}

    def get_extra_grade(self, column_id: int, student_id: int) -> ExtraGrade | None:
        return self.session.get(ExtraGrade, (column_id, student_id))

    def final_grades(self, journal_id: int) -> list[FinalGrade]:
        return list(self.session.scalars(select(FinalGrade).where(FinalGrade.journal_id == journal_id)))

    def get_final_grade(self, journal_id: int, student_id: int, kind) -> FinalGrade | None:
        return self.session.get(FinalGrade, (journal_id, student_id, kind))

    # --- запис ---

    def add(self, obj) -> None:
        self.session.add(obj)
        self.session.flush()

    def delete(self, obj) -> None:
        self.session.delete(obj)
        self.session.flush()

    def delete_journal_contents(self, journal_id: int) -> None:
        """Підсумкові оцінки, extra-стовпчики й уроки журналу (відмітки уроків і оцінки
        extra-стовпчиків видаляє БД каскадом)."""
        self.session.execute(delete(FinalGrade).where(FinalGrade.journal_id == journal_id))
        self.session.execute(delete(ExtraColumn).where(ExtraColumn.journal_id == journal_id))
        self.session.execute(delete(Lesson).where(Lesson.journal_id == journal_id))
        self.session.flush()
        self.session.expire_all()

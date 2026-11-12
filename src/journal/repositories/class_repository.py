"""Доступ до класів і учнів. Лише запити — без бізнес-правил."""
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from journal.models import FinalGrade, Journal, LessonEntry, SchoolClass, Student


class ClassRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def classes_for_teacher(self, teacher_id: int, include_archived: bool) -> list[SchoolClass]:
        query = select(SchoolClass).where(SchoolClass.teacher_id == teacher_id)
        if not include_archived:
            query = query.where(SchoolClass.archived.is_(False))
        return list(self.session.scalars(query))

    def get_class(self, class_id: int) -> SchoolClass | None:
        return self.session.get(SchoolClass, class_id)

    def get_student(self, student_id: int) -> Student | None:
        return self.session.get(Student, student_id)

    def students(self, class_id: int) -> list[Student]:
        return list(self.session.scalars(select(Student).where(Student.class_id == class_id)))

    def active_student_counts(self, class_ids: list[int]) -> dict[int, int]:
        if not class_ids:
            return {}
        rows = self.session.execute(
            select(Student.class_id, func.count())
            .where(Student.class_id.in_(class_ids), Student.archived.is_(False))
            .group_by(Student.class_id)
        )
        return {class_id: count for class_id, count in rows}

    def journals_of_class(self, class_id: int) -> list[Journal]:
        return list(self.session.scalars(select(Journal).where(Journal.class_id == class_id)))

    def has_journals(self, class_id: int) -> bool:
        return bool(self.session.scalar(select(exists().where(Journal.class_id == class_id))))

    def student_has_records(self, student_id: int) -> bool:
        """Чи є в учня відмітки на уроках або підсумкові оцінки."""
        has_entries = exists().where(LessonEntry.student_id == student_id)
        has_finals = exists().where(FinalGrade.student_id == student_id)
        return bool(self.session.scalar(select(has_entries | has_finals)))

    def add(self, obj) -> None:
        self.session.add(obj)
        self.session.flush()

    def delete(self, obj) -> None:
        self.session.delete(obj)
        self.session.flush()

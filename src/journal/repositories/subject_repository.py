"""Довідник предметів. Лише запити."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journal.models import Subject


class SubjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def all(self) -> list[Subject]:
        return list(self.session.scalars(select(Subject)))

    def get_by_name(self, name: str) -> Subject | None:
        return self.session.scalars(
            select(Subject).where(func.lower(Subject.name) == name.lower())
        ).first()

    def add(self, subject: Subject) -> Subject:
        self.session.add(subject)
        self.session.flush()
        return subject

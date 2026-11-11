"""Доступ до таблиці teachers. Репозиторій лише читає/пише — без бізнес-правил."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journal.models import Teacher


class TeacherRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Teacher)) or 0

    def get_by_username(self, username: str) -> Teacher | None:
        return self.session.scalars(
            select(Teacher).where(func.lower(Teacher.username) == username.lower())
        ).one_or_none()

    def add(self, teacher: Teacher) -> Teacher:
        self.session.add(teacher)
        self.session.flush()
        return teacher

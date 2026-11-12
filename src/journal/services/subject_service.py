"""Предмети: список і додавання власного предмета викладачкою.

Початкові предмети (Алгебра, Геометрія, Математика, Фізика) додають міграції.
Видалення предметів свідомо не реалізовано: автор його не просив, а на предмет
можуть посилатися журнали з оцінками.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from journal.models import Subject
from journal.repositories.subject_repository import SubjectRepository
from journal.services.class_service import normalize_name
from journal.services.ua_sort import ukrainian_sort_key

MAX_SUBJECT_NAME = 50


class SubjectError(Exception):
    """Помилка з повідомленням, яке можна показати користувачу."""


@dataclass(frozen=True)
class SubjectInfo:
    id: int
    name: str


class SubjectService:
    def __init__(self, session: Session) -> None:
        self.repo = SubjectRepository(session)

    def list_subjects(self) -> list[SubjectInfo]:
        """Усі предмети за українським алфавітом."""
        subjects = sorted(self.repo.all(), key=lambda s: ukrainian_sort_key(s.name))
        return [SubjectInfo(s.id, s.name) for s in subjects]

    def add_subject(self, name: str) -> SubjectInfo:
        name = normalize_name(name)
        if not name:
            raise SubjectError("Вкажіть назву предмета")
        if len(name) > MAX_SUBJECT_NAME:
            raise SubjectError(f"Назва предмета — не довше {MAX_SUBJECT_NAME} символів")
        if self.repo.get_by_name(name) is not None:
            raise SubjectError(f"Предмет «{name}» уже є")
        subject = self.repo.add(Subject(name=name))
        return SubjectInfo(subject.id, subject.name)

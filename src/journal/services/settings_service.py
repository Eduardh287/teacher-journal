"""Налаштування викладача: межі семестрів (етап 5.2, docs/specs/stage-5.2.md).

Контракт написав оркестратор; реалізацію робить агент A.
"""
from sqlalchemy.orm import Session

from journal.services.semesters import SemesterBoundaries


class SettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_semesters(self, teacher_id: int) -> SemesterBoundaries:
        """Глобальні межі семестрів викладача."""
        raise NotImplementedError

    def set_semesters(self, teacher_id: int, boundaries: SemesterBoundaries) -> int:
        """Зберігає межі й застосовує їх до всіх журналів класів НЕ в архіві
        (перераховує lessons.semester). Повертає кількість оновлених журналів.
        Помилки: SemesterError (неправильні межі), SemesterConflict (уроки в канікулах) —
        тоді нічого не зберігається."""
        raise NotImplementedError

"""Перехід на новий навчальний рік (етап 5.2, docs/specs/stage-5.2.md).

Рішення автора: 9-А → НОВИЙ клас 10-А на наступний рік з тими самими активними учнями
(нові записи учнів), старий клас разом із журналами — в архів без змін; 11-й клас і класи
без номера — в архів. Пропонується з 1 серпня; у вікні є галочка «створити такі самі журнали».
Контракт написав оркестратор; реалізацію робить агент A.
"""
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

RolloverAction = Literal["promote", "archive"]


@dataclass(frozen=True)
class RolloverItem:
    class_id: int
    class_name: str
    school_year: str
    action: RolloverAction
    new_name: str | None  # «10-А» для promote, інакше None
    new_year: str | None  # «2027-2028» для promote
    target_exists: bool  # 10-А на новий рік уже є → лише архівуємо старий
    student_count: int  # активних учнів
    subject_names: tuple[str, ...]  # предмети журналів старого класу (для галочки)


class RolloverService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def plan(self, teacher_id: int, today: date) -> list[RolloverItem]:
        """Що буде зроблено (без запису). Порожній список — пропонувати нічого."""
        raise NotImplementedError

    def apply(self, teacher_id: int, today: date, copy_journals: bool = False) -> list[RolloverItem]:
        """Виконує план в одній транзакції; повторний виклик нічого не робить.
        copy_journals=True — для нового класу створюються порожні журнали тих самих предметів."""
        raise NotImplementedError

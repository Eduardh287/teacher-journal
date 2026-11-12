"""Перехід на новий навчальний рік (етап 5.2, docs/specs/stage-5.2.md).

Рішення автора: 9-А → НОВИЙ клас 10-А на наступний рік з тими самими активними учнями
(нові записи учнів), старий клас разом із журналами — в архів без змін; 11-й клас і класи
без номера — в архів. Пропонується з 1 серпня; у вікні є галочка «створити такі самі журнали».
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from journal.models import Journal, SchoolClass, Student
from journal.repositories.class_repository import ClassRepository
from journal.repositories.journal_repository import JournalRepository
from journal.services.boundaries_rows import boundaries_of, set_boundaries
from journal.services.class_service import MAX_CLASS_NAME, ClassService
from journal.services.journal_types import JournalError
from journal.services.semesters import next_school_year, rollover_due
from journal.services.ua_sort import class_name_key, ukrainian_sort_key

RolloverAction = Literal["promote", "archive"]

LAST_GRADE = 11  # після 11-го класу навчання завершується
_NAME_RE = re.compile(r"^(\d{1,2})(.*)$")


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
        self.classes = ClassRepository(session)
        self.journals = JournalRepository(session)

    def plan(self, teacher_id: int, today: date) -> list[RolloverItem]:
        """Що буде зроблено (без запису). Порожній список — пропонувати нічого."""
        all_classes = self.classes.classes_for_teacher(teacher_id, include_archived=True)
        taken = {(c.name.casefold(), c.school_year) for c in all_classes}
        due = [c for c in all_classes if not c.archived and rollover_due(c.school_year, today)]
        due.sort(key=lambda c: (c.school_year, class_name_key(c.name)))
        counts = self.classes.active_student_counts([c.id for c in due])
        return [self._item(c, taken, counts.get(c.id, 0)) for c in due]

    def apply(self, teacher_id: int, today: date, copy_journals: bool = False) -> list[RolloverItem]:
        """Виконує план в одній транзакції; повторний виклик нічого не робить.
        Клас, що «відстав» на кілька років, просувається на один рік за запуск (наступний запуск — ще на рік).
        copy_journals=True — для нового класу створюються порожні журнали тих самих предметів."""
        items = self.plan(teacher_id, today)
        if not items:
            return items
        teacher = self.journals.get_teacher(teacher_id)
        if teacher is None:
            raise JournalError("Викладача не знайдено")
        class_service = ClassService(self.session)
        for item in items:
            old = self.classes.get_class(item.class_id)
            if item.action == "promote" and not item.target_exists:
                new = SchoolClass(teacher_id=teacher_id, name=item.new_name, school_year=item.new_year)
                self.classes.add(new)
                self._copy_students(old, new)
                class_service.renumber(new.id)
                if copy_journals:
                    for journal in self.journals.journals_of_class(old.id):
                        copy = Journal(class_id=new.id, subject_id=journal.subject_id)
                        set_boundaries(copy, boundaries_of(teacher))  # поточні межі з Налаштувань
                        self.journals.add(copy)
            old.archived = True
        self.session.flush()
        return items

    def _item(self, c: SchoolClass, taken: set[tuple[str, str]], students: int) -> RolloverItem:
        subjects = tuple(
            sorted(
                (j.subject.name for j in self.journals.journals_of_class(c.id)),
                key=ukrainian_sort_key,
            )
        )
        match = _NAME_RE.match(c.name)
        grade = int(match.group(1)) if match else 0
        new_name = f"{grade + 1}{match.group(2)}" if match else ""
        # Задовга нова назва (9-А… на 20 символів → 10-А… на 21) — лише архів, без помилки БД.
        if match and 1 <= grade < LAST_GRADE and len(new_name) <= MAX_CLASS_NAME:
            new_year = next_school_year(c.school_year)
            key = (new_name.casefold(), new_year)
            exists = key in taken
            taken.add(key)  # «9-А» і «09-А» обидва → «10-А»: другий отримає target_exists
            return RolloverItem(
                c.id, c.name, c.school_year, "promote", new_name, new_year, exists, students, subjects
            )
        return RolloverItem(c.id, c.name, c.school_year, "archive", None, None, False, students, subjects)

    def _copy_students(self, old: SchoolClass, new: SchoolClass) -> None:
        """Активні учні старого класу стають НОВИМИ записами (історія оцінок лишається в старому)."""
        for student in self.classes.students(old.id):
            if not student.archived:
                self.session.add(Student(class_id=new.id, full_name=student.full_name, position=0))
        self.session.flush()

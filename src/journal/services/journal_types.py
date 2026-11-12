"""Спільний контракт етапу 5: DTO, помилки і інтерфейс сервісу журналів.

Цей файл — «договір» між сервісом (journal_service.py) та інтерфейсом (ui/journal_*.py):
обидві сторони пишуться окремо й паралельно, але проти однакових типів.
Специфікація: docs/specs/stage-5.md.
"""
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from journal.services.class_service import StudentInfo
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries, VacationDateError

AttendanceCode = Literal["present", "absent", "sick", "late"]
LessonTypeCode = Literal["regular", "test", "lab", "independent"]

MAX_TOPIC = 255
MAX_COMMENT = 500


class JournalError(Exception):
    """Помилка з повідомленням, яке можна показати користувачу."""


class JournalNotFound(JournalError):
    """Журнал не існує або належить іншому викладачу («Журнал не знайдено»)."""


class LessonNotFound(JournalError):
    """Урок не існує або належить іншому викладачу («Урок не знайдено»)."""


def semester_for_date(d: date, boundaries: SemesterBoundaries = DEFAULT_BOUNDARIES) -> int:
    """Номер семестру для дати за межами семестрів (етап 5.2). Канікули → JournalError."""
    try:
        return boundaries.semester_for(d)
    except VacationDateError as error:
        raise JournalError(str(error)) from None


@dataclass(frozen=True)
class LessonConflict:
    """Урок, який після зміни меж семестрів потрапив би в канікули."""

    journal_id: int
    class_name: str
    school_year: str
    subject_name: str
    lesson_date: date


class SemesterConflict(JournalError):
    """Зміну меж не збережено: є уроки, що потрапляють у канікули (рішення автора)."""

    def __init__(self, conflicts: list[LessonConflict]) -> None:
        super().__init__("Зміну не збережено: уроки потрапляють у канікули")
        self.conflicts = conflicts


@dataclass(frozen=True)
class JournalInfo:
    id: int
    class_id: int
    class_name: str
    school_year: str
    subject_id: int
    subject_name: str
    class_archived: bool
    lesson_count: int
    boundaries: SemesterBoundaries = DEFAULT_BOUNDARIES  # межі семестрів цього журналу


@dataclass(frozen=True)
class JournalCandidate:
    """Пара «клас × предмет», для якої журналу ще немає."""

    class_id: int
    class_name: str
    school_year: str
    subject_id: int
    subject_name: str


@dataclass(frozen=True)
class LessonInfo:
    id: int
    lesson_date: date
    semester: int
    lesson_type: LessonTypeCode
    topic: str | None
    entry_count: int


@dataclass(frozen=True)
class CellInfo:
    attendance: AttendanceCode
    grade: int | None
    comment: str | None


@dataclass(frozen=True)
class GridData:
    """Усе, що потрібно таблиці журналу за один семестр.

    cells: ключ (student_id, lesson_id); відсутній ключ = порожня клітинка
    (присутній, без оцінки й коментаря).
    """

    journal: JournalInfo
    semester: int
    students: list[StudentInfo]
    lessons: list[LessonInfo]
    cells: dict[tuple[int, int], CellInfo]


class JournalApi(Protocol):
    """Інтерфейс сервісу журналів. Його реалізують JournalService (БД) і FakeJournalService (тести UI)."""

    def list_journals(self, teacher_id: int, include_archived: bool = False) -> list[JournalInfo]: ...

    def list_journal_candidates(self, teacher_id: int) -> list[JournalCandidate]: ...

    def create_journal(self, teacher_id: int, class_id: int, subject_id: int) -> JournalInfo: ...

    def delete_journal(
        self, teacher_id: int, journal_id: int, with_contents: bool = False
    ) -> None:
        """Видаляє журнал. З уроками/оцінками — лише якщо with_contents=True
        (UI передає його тільки після підтвердження словом «видалити»)."""
        ...

    def get_grid(self, teacher_id: int, journal_id: int, semester: int) -> GridData: ...

    def create_lesson(
        self,
        teacher_id: int,
        journal_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode = "regular",
        topic: str | None = None,
    ) -> LessonInfo: ...

    def update_lesson(
        self,
        teacher_id: int,
        lesson_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode,
        topic: str | None,
    ) -> LessonInfo: ...

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None: ...

    def set_journal_semesters(
        self, teacher_id: int, journal_id: int, boundaries: SemesterBoundaries
    ) -> JournalInfo:
        """Межі семестрів окремого журналу — лише для архівного класу (журнали в роботі
        беруть межі з Налаштувань). Конфлікт з уроками → SemesterConflict."""
        ...

    def set_cell(
        self,
        teacher_id: int,
        lesson_id: int,
        student_id: int,
        attendance: AttendanceCode,
        grade: int | None,
        comment: str | None,
    ) -> CellInfo | None: ...

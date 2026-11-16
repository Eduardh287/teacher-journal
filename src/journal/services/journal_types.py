"""Спільний контракт етапів 5–6: DTO, помилки і інтерфейс сервісу журналів.

Цей файл — «договір» між сервісом (journal_service.py) та інтерфейсом (ui/journal_*.py):
обидві сторони пишуться окремо й паралельно, але проти однакових типів.
Специфікації: docs/specs/stage-5.md, docs/specs/stage-6.md.
"""
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from journal.services.class_service import StudentInfo
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries, VacationDateError

AttendanceCode = Literal["present", "absent", "sick", "late"]
# test = «Контрольна робота»; quiz = «Тест»; project = «Проєкт» (етап 6)
LessonTypeCode = Literal["regular", "test", "lab", "independent", "quiz", "project"]
# Стовпчики без дати (етап 6): тематична, зошит; підсумкові: семестрова, річна.
ExtraColumnKind = Literal["thematic", "notebook"]
GridColumnKind = Literal["lesson", "thematic", "notebook", "semester", "annual"]

MAX_TOPIC = 255
MAX_COMMENT = 500
MAX_HOMEWORK = 500


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
    boundaries: SemesterBoundaries  # межі семестрів цього журналу


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
    homework: str | None
    number: int  # наскрізний номер уроку за навчальний рік (1-based; лише уроки з датою)


@dataclass(frozen=True)
class CellInfo:
    attendance: AttendanceCode
    grade: int | None
    comment: str | None


@dataclass(frozen=True)
class ExtraColumnInfo:
    """Стовпчик без дати: «Тематична» або «Зошит».

    after_date — прихований ключ сортування (дата уроку, після якого стоїть стовпчик);
    користувачу не показується і вручну не задається.
    """

    id: int
    kind: ExtraColumnKind
    semester: int
    after_date: date
    ordinal: int  # порядковий номер цього виду в семестрі (1, 2, …)
    grade_count: int  # кількість збережених оцінок у extra_grades


@dataclass(frozen=True)
class GridColumn:
    """Стовпчик таблиці в порядку відображення. id: урок / extra-стовпчик; для semester/annual — None."""

    kind: GridColumnKind
    id: int | None


# Ключ обчислюваної клітинки: ("thematic", id) | ("notebook", id) | ("semester", 1|2) | ("annual", 0)
ComputedKey = tuple[str, int]


@dataclass(frozen=True)
class ComputedCell:
    """Клітинка тематичної / зошита / семестрової / річної.

    auto — пораховане значення (None — немає), auto_na — пораховано «н/а»;
    override / override_na — виставлено вручну (для «Зошита» override — це сама оцінка).
    total / count — сума й кількість складових середнього (для підказки «Середнє 7,50 (6 оцінок)»).
    «н/а» — лише позначка: у всіх розрахунках н/а = 0 (рішення автора).
    """

    auto: int | None
    auto_na: bool
    total: int
    count: int
    override: int | None
    override_na: bool

    @property
    def is_manual(self) -> bool:
        return self.override is not None or self.override_na

    @property
    def is_na(self) -> bool:
        return self.override_na if self.is_manual else self.auto_na

    @property
    def value(self) -> int | None:
        """Ефективна оцінка (None, якщо н/а чи порожньо)."""
        return self.override if self.is_manual else self.auto


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
    columns: list[GridColumn]  # уроки + extra-стовпчики за порядком, далі підсумкові
    extra_columns: list[ExtraColumnInfo]
    computed: dict[tuple[int, ComputedKey], ComputedCell]  # (student_id, key)


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
        homework: str | None = None,
    ) -> LessonInfo: ...

    def update_lesson(
        self,
        teacher_id: int,
        lesson_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode,
        topic: str | None,
        homework: str | None = None,
    ) -> LessonInfo: ...

    def set_homework(self, teacher_id: int, lesson_id: int, homework: str | None) -> LessonInfo:
        """Швидке редагування д/з з панелі уроків (trim; порожнє → None; > 500 → помилка)."""
        ...

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None:
        """Урок з будь-якою відміткою чи оцінкою не видаляється (рішення викладачки):
        «Урок має оцінки чи позначки (N) — його не можна видалити. Спершу очистьте клітинки цього уроку.»"""
        ...

    def create_column(
        self, teacher_id: int, journal_id: int, kind: ExtraColumnKind, after_lesson_id: int
    ) -> ExtraColumnInfo:
        """Додає «Тематичну» / «Зошит» після уроку (без дати)."""
        ...

    def move_column(self, teacher_id: int, column_id: int, after_lesson_id: int) -> ExtraColumnInfo: ...

    def delete_column(self, teacher_id: int, column_id: int) -> None:
        """«Зошит» з оцінками не видаляється; тематична — так (ручні оцінки зникають)."""
        ...

    def set_override(
        self,
        teacher_id: int,
        journal_id: int,
        student_id: int,
        key: ComputedKey,
        grade: int | None,
        na: bool = False,
    ) -> dict[ComputedKey, ComputedCell]:
        """Ручна оцінка в обчислюваній клітинці (або оцінка «Зошита»). grade=None і na=False —
        повернути автоматичне значення. Повертає всі обчислювані клітинки цього учня."""
        ...

    def student_computed(
        self, teacher_id: int, journal_id: int, student_id: int
    ) -> dict[ComputedKey, ComputedCell]:
        """Обчислювані клітинки учня (UI оновлює рядок після кожного set_cell)."""
        ...

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

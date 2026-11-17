"""Класи та учні: створення, списки, імпорт списку учнів, архівування.

Правила (рішення рецензента Fable, етап 3):
- учні завжди впорядковані за українським алфавітом; position = номер у паперовому журналі (1..N
  серед активних), у вибулих учнів position = 0;
- видаляти можна лише те, з чим не пов'язано жодних даних, інакше — архів;
- кожен метод перевіряє, що клас/учень належить викладачу teacher_id.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from journal.models import SchoolClass, Student
from journal.repositories.class_repository import ClassRepository
from journal.repositories.journal_repository import JournalRepository
from journal.services.ua_sort import class_name_key, ukrainian_sort_key

MAX_CLASS_NAME = 20
MAX_STUDENT_NAME = 150
MAX_STUDENTS_PER_CLASS = 60

_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")
# «1. Ім'я», «2) Ім'я», «3 Ім'я», «4.Ім'я» → «Ім'я»
_LEADING_NUMBER_RE = re.compile(r"^\s*\d+\s*(?:[.)]\s*|\s+)")
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'"})
# Невидимі символи, які трапляються в тексті з PDF/Word/macOS: zero-width, BOM, м'який перенос.
_INVISIBLE = str.maketrans({c: None for c in "\u200b\u200c\u200d\u2060\ufeff\u00ad"})

# Дозволені кольори рядка учня (ключі theme.ROW_COLORS; збіг перевіряє тест). Дублюються в CHECK міграції.
ROW_COLOR_KEYS = ("yellow", "green", "blue", "pink", "purple", "orange")

RemovalMode = Literal["delete", "archive"]


class ClassError(Exception):
    """Помилка з повідомленням, яке можна показати користувачу."""


class ClassNotFound(ClassError):
    """Клас не існує або належить іншому викладачу."""


# ---------- Об'єкти для інтерфейсу (не ORM, щоб UI не залежав від сесії БД) ----------


@dataclass(frozen=True)
class ClassInfo:
    id: int
    name: str
    school_year: str
    archived: bool
    student_count: int


@dataclass(frozen=True)
class StudentInfo:
    id: int
    full_name: str
    position: int
    archived: bool
    row_color: str | None = None


@dataclass(frozen=True)
class ImportResult:
    added: int
    skipped_duplicates: int


# ---------- Чисті функції ----------


def default_school_year(today: date) -> str:
    """З серпня — новий навчальний рік (класи налаштовують до 1 вересня)."""
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{start + 1}"


def school_year_choices(today: date) -> list[str]:
    """Попередній, поточний і наступний навчальні роки."""
    start = int(default_school_year(today)[:4])
    return [f"{y}-{y + 1}" for y in (start - 1, start, start + 1)]


def normalize_name(text: str) -> str:
    """Прибирає зайві пробіли й невидимі символи, уніфікує апострофи.

    NFC: «й»/«ї», вставлені з PDF чи macOS як «и» + знак, стають однією літерою —
    інакше вони сортувалися б неправильно і не розпізнавалися як дублікати.
    """
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE).translate(_APOSTROPHES)
    return " ".join(text.split())


def _parse_lines(text: str) -> list[tuple[int, str]]:
    """(номер рядка, ім'я) для кожного непорожнього рядка; нумерацію на початку прибирає."""
    result = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        # Невидимі символи прибираємо ДО пошуку номера: BOM на початку рядка заважав би йому.
        line = raw.translate(_INVISIBLE).replace("\t", " ")
        name = normalize_name(_LEADING_NUMBER_RE.sub("", line, count=1))
        if any(ch.isalpha() for ch in name):  # «1», «—», «№» з таблиці Word — не учні
            result.append((line_no, name))
    return result


def _validate_year(school_year: str) -> str:
    match = _YEAR_RE.match(school_year.strip())
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ClassError("Навчальний рік має бути у форматі «2026-2027»")
    return school_year.strip()


def _validate_class_name(name: str) -> str:
    name = normalize_name(name)
    if not name:
        raise ClassError("Вкажіть назву класу")
    if len(name) > MAX_CLASS_NAME:
        raise ClassError(f"Назва класу — не довше {MAX_CLASS_NAME} символів")
    return name


def _validate_student_name(full_name: str) -> str:
    full_name = normalize_name(full_name)
    if not full_name:
        raise ClassError("Вкажіть прізвище та ім'я")
    if len(full_name) > MAX_STUDENT_NAME:
        raise ClassError(f"Ім'я учня — не довше {MAX_STUDENT_NAME} символів")
    return full_name


# ---------- Сервіс ----------


class ClassService:
    def __init__(self, session: Session) -> None:
        self.repo = ClassRepository(session)

    # --- класи ---

    def list_classes(self, teacher_id: int, include_archived: bool = False) -> list[ClassInfo]:
        classes = self.repo.classes_for_teacher(teacher_id, include_archived)
        counts = self.repo.active_student_counts([c.id for c in classes])
        # Новіші роки першими, у межах року — природний порядок назв.
        classes.sort(key=lambda c: class_name_key(c.name))
        classes.sort(key=lambda c: c.school_year, reverse=True)
        return [_class_info(c, counts.get(c.id, 0)) for c in classes]

    def create_class(self, teacher_id: int, name: str, school_year: str) -> ClassInfo:
        name = _validate_class_name(name)
        school_year = _validate_year(school_year)
        self._ensure_unique_class(teacher_id, name, school_year, exclude_id=None)
        school_class = SchoolClass(teacher_id=teacher_id, name=name, school_year=school_year)
        self.repo.add(school_class)
        return _class_info(school_class, 0)

    def update_class(self, teacher_id: int, class_id: int, name: str, school_year: str) -> ClassInfo:
        school_class = self._own_class(teacher_id, class_id, editable=True)
        name = _validate_class_name(name)
        school_year = _validate_year(school_year)
        self._ensure_unique_class(teacher_id, name, school_year, exclude_id=class_id)
        school_class.name = name
        school_class.school_year = school_year
        self.repo.session.flush()
        return _class_info(school_class, self._active_count(class_id))

    def set_class_archived(self, teacher_id: int, class_id: int, archived: bool) -> None:
        """Архівує клас чи повертає його. Повернення синхронізує межі семестрів його
        журналів з Налаштуваннями; конфлікт з уроками → SemesterConflict, клас не повертається."""
        school_class = self._own_class(teacher_id, class_id)
        if school_class.archived and not archived:
            self._resync_boundaries(school_class)
        school_class.archived = archived
        self.repo.session.flush()

    def class_removal_mode(self, teacher_id: int, class_id: int) -> RemovalMode:
        self._own_class(teacher_id, class_id)
        return "archive" if self.repo.has_journals(class_id) else "delete"

    def delete_class(self, teacher_id: int, class_id: int) -> None:
        school_class = self._own_class(teacher_id, class_id)
        if self.repo.has_journals(class_id):
            raise ClassError("У класу є журнали — його можна лише перенести в архів")
        self.repo.delete(school_class)

    # --- учні ---

    def list_students(self, teacher_id: int, class_id: int) -> list[StudentInfo]:
        self._own_class(teacher_id, class_id)
        students = self.repo.students(class_id)
        students.sort(key=lambda s: (s.archived, s.position if not s.archived else 0,
                                     ukrainian_sort_key(s.full_name)))
        return [_student_info(s) for s in students]

    def add_student(self, teacher_id: int, class_id: int, full_name: str) -> StudentInfo:
        self._own_class(teacher_id, class_id, editable=True)
        full_name = _validate_student_name(full_name)
        existing = self.repo.students(class_id)
        match = _find_by_name(existing, full_name)
        if match is not None:
            if match.archived:
                raise ClassError("Цей учень позначений як вибулий — поверніть його зі списку")
            raise ClassError("Такий учень уже є в цьому класі")
        if sum(not s.archived for s in existing) >= MAX_STUDENTS_PER_CLASS:
            raise ClassError(f"У класі не може бути більше {MAX_STUDENTS_PER_CLASS} учнів")
        student = Student(class_id=class_id, full_name=full_name, position=0)
        self.repo.add(student)
        self._renumber(class_id)
        return _student_info(student)

    def preview_import(self, teacher_id: int, class_id: int, text: str) -> ImportResult:
        """Скільки учнів буде додано — без запису в БД (для живої підказки в діалозі)."""
        self._own_class(teacher_id, class_id)
        new_names, skipped = self._plan_import(class_id, text)
        return ImportResult(added=len(new_names), skipped_duplicates=skipped)

    def import_students(self, teacher_id: int, class_id: int, text: str) -> ImportResult:
        """Додає всіх учнів зі списку в одній транзакції: або всіх, або нікого."""
        self._own_class(teacher_id, class_id, editable=True)
        new_names, skipped = self._plan_import(class_id, text)
        active = sum(not s.archived for s in self.repo.students(class_id))
        if active + len(new_names) > MAX_STUDENTS_PER_CLASS:
            raise ClassError(f"У класі не може бути більше {MAX_STUDENTS_PER_CLASS} учнів")
        for name in new_names:
            self.repo.session.add(Student(class_id=class_id, full_name=name, position=0))
        self.repo.session.flush()
        self._renumber(class_id)
        return ImportResult(added=len(new_names), skipped_duplicates=skipped)

    def rename_student(self, teacher_id: int, student_id: int, full_name: str) -> StudentInfo:
        student = self._own_student(teacher_id, student_id, editable=True)
        full_name = _validate_student_name(full_name)
        others = [s for s in self.repo.students(student.class_id) if s.id != student.id]
        if _find_by_name(others, full_name) is not None:
            raise ClassError("Такий учень уже є в цьому класі")
        student.full_name = full_name
        self.repo.session.flush()
        self._renumber(student.class_id)
        return _student_info(student)

    def student_removal_mode(self, teacher_id: int, student_id: int) -> RemovalMode:
        self._own_student(teacher_id, student_id)
        return "archive" if self.repo.student_has_records(student_id) else "delete"

    def delete_student(self, teacher_id: int, student_id: int) -> None:
        student = self._own_student(teacher_id, student_id, editable=True)
        if self.repo.student_has_records(student_id):
            raise ClassError("Учень має оцінки чи відмітки — його можна лише позначити як вибулого")
        class_id = student.class_id
        self.repo.delete(student)
        self._renumber(class_id)

    def set_student_archived(self, teacher_id: int, student_id: int, archived: bool) -> None:
        student = self._own_student(teacher_id, student_id, editable=True)
        if not archived and student.archived:
            active = self._active_count(student.class_id)
            if active >= MAX_STUDENTS_PER_CLASS:
                raise ClassError(f"У класі не може бути більше {MAX_STUDENTS_PER_CLASS} учнів")
        student.archived = archived
        self.repo.session.flush()
        self._renumber(student.class_id)

    def set_student_color(self, teacher_id: int, student_id: int, color: str | None) -> StudentInfo:
        """Колір рядка учня в журналах; None — без кольору. Дозволено й для вибулих і для архівного класу."""
        if color is not None and color not in ROW_COLOR_KEYS:
            raise ClassError("Невідомий колір")
        student = self._own_student(teacher_id, student_id)
        student.row_color = color
        self.repo.session.flush()
        return _student_info(student)

    # --- допоміжне ---

    def _own_class(self, teacher_id: int, class_id: int, editable: bool = False) -> SchoolClass:
        school_class = self.repo.get_class(class_id)
        if school_class is None or school_class.teacher_id != teacher_id:
            raise ClassNotFound("Клас не знайдено")
        if editable and school_class.archived:
            raise ClassError("Клас в архіві — спершу поверніть його")
        return school_class

    def _own_student(self, teacher_id: int, student_id: int, editable: bool = False) -> Student:
        student = self.repo.get_student(student_id)
        if student is None:
            raise ClassNotFound("Учня не знайдено")
        try:
            self._own_class(teacher_id, student.class_id, editable=editable)
        except ClassNotFound:
            raise ClassNotFound("Учня не знайдено") from None
        return student

    def _ensure_unique_class(
        self, teacher_id: int, name: str, school_year: str, exclude_id: int | None
    ) -> None:
        for other in self.repo.classes_for_teacher(teacher_id, include_archived=True):
            if (
                other.id != exclude_id
                and other.school_year == school_year
                and other.name.casefold() == name.casefold()
            ):
                raise ClassError(f"Клас «{name}» на {school_year} навчальний рік уже існує")

    def _plan_import(self, class_id: int, text: str) -> tuple[list[str], int]:
        """Які імена додати і скільки дублікатів пропустити (без запису)."""
        lines = _parse_lines(text)
        for line_no, name in lines:
            if len(name) > MAX_STUDENT_NAME:
                raise ClassError(f"Рядок {line_no} задовгий (понад {MAX_STUDENT_NAME} символів)")
        seen = {s.full_name.casefold() for s in self.repo.students(class_id)}
        new_names, skipped = [], 0
        for _, name in lines:
            folded = name.casefold()
            if folded in seen:
                skipped += 1
            else:
                seen.add(folded)
                new_names.append(name)
        return new_names, skipped

    def _resync_boundaries(self, school_class: SchoolClass) -> None:
        """Журнали повернутого класу беруть глобальні межі викладача."""
        # Імпорт тут: settings_service залежить від journal_types, а той — від цього модуля.
        from journal.services.boundaries_rows import boundaries_of
        from journal.services.settings_service import apply_boundaries

        journals_repo = JournalRepository(self.repo.session)
        apply_boundaries(
            journals_repo, journals_repo.journals_of_class(school_class.id), boundaries_of(school_class.teacher)
        )

    def renumber(self, class_id: int) -> None:
        """Перенумерація активних учнів класу (для переходу на новий рік)."""
        self._renumber(class_id)

    def _active_count(self, class_id: int) -> int:
        return sum(not s.archived for s in self.repo.students(class_id))

    def _renumber(self, class_id: int) -> None:
        """Інваріант: активні учні мають номери 1..N за алфавітом, вибулі — 0."""
        students = self.repo.students(class_id)
        # id — для стабільного порядку, якщо імена відрізняються лише апострофом.
        active = sorted((s for s in students if not s.archived),
                        key=lambda s: (ukrainian_sort_key(s.full_name), s.id))
        for number, student in enumerate(active, start=1):
            student.position = number
        for student in students:
            if student.archived:
                student.position = 0
        self.repo.session.flush()


def _find_by_name(students: list[Student], full_name: str) -> Student | None:
    folded = full_name.casefold()
    return next((s for s in students if s.full_name.casefold() == folded), None)


def _class_info(c: SchoolClass, student_count: int) -> ClassInfo:
    return ClassInfo(c.id, c.name, c.school_year, c.archived, student_count)


def _student_info(s: Student) -> StudentInfo:
    return StudentInfo(s.id, s.full_name, s.position, s.archived, s.row_color)

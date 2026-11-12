"""Межі семестрів (з точністю до місяця) і навчальний рік.

Рішення автора (12.11.2026): межі задаються місяцями в Налаштуваннях;
за замовчуванням I семестр — вересень–грудень, II — січень–червень, решта — канікули.
Перехід на новий навчальний рік пропонується з 1 серпня. Специфікація: docs/specs/stage-5.2.md.
"""
from dataclasses import dataclass
from datetime import date

MONTHS_UA = (
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
)
ROLLOVER_MONTH = 8  # перехід на новий рік пропонується з 1 серпня (рішення автора)


class SemesterError(Exception):
    """Неправильні межі семестрів (повідомлення можна показати користувачу)."""


class VacationDateError(Exception):
    """Дата припадає на канікули."""


@dataclass(frozen=True)
class SemesterBoundaries:
    """Місяці початку й кінця кожного семестру (1–12, включно)."""

    s1_start: int
    s1_end: int
    s2_start: int
    s2_end: int

    def _offset(self, month: int) -> int:
        """Скільки місяців минуло від початку I семестру (0..11)."""
        return (month - self.s1_start) % 12

    def validate(self) -> "SemesterBoundaries":
        for month in (self.s1_start, self.s1_end, self.s2_start, self.s2_end):
            if not 1 <= month <= 12:
                raise SemesterError("Місяць має бути від 1 до 12")
        off = self._offset
        if not off(self.s1_end) < off(self.s2_start) <= off(self.s2_end):
            raise SemesterError("Семестри не можуть перетинатися; I семестр має передувати II")
        # Перехід на новий рік — з 1 серпня (рішення автора), тож рік має вкладатися між серпнями.
        if self.s1_start < ROLLOVER_MONTH or self.s2_end >= ROLLOVER_MONTH or self.s2_start >= ROLLOVER_MONTH:
            raise SemesterError(
                "I семестр має починатися з серпня або пізніше, а II — закінчуватися до серпня"
            )
        return self

    def semester_of_month(self, month: int) -> int | None:
        """1, 2 або None (канікули)."""
        off = self._offset(month)
        if off <= self._offset(self.s1_end):
            return 1
        if self._offset(self.s2_start) <= off <= self._offset(self.s2_end):
            return 2
        return None

    def semester_for(self, d: date) -> int:
        semester = self.semester_of_month(d.month)
        if semester is None:
            raise VacationDateError("Ця дата припадає на канікули: уроки на неї не створюються")
        return semester

    def calendar_year(self, school_year: str, month: int) -> int:
        """Календарний рік місяця в межах навчального року «2026-2027»."""
        first = int(school_year[:4])
        return first if month >= self.s1_start else first + 1

    def contains(self, school_year: str, d: date) -> bool:
        """Чи належить дата навчальному року (і не канікулам)."""
        return (
            self.semester_of_month(d.month) is not None
            and self.calendar_year(school_year, d.month) == d.year
        )

    def label(self) -> str:
        """«I: вересень–грудень · II: січень–червень»."""
        m = MONTHS_UA
        return (
            f"I: {m[self.s1_start - 1]}–{m[self.s1_end - 1]} · "
            f"II: {m[self.s2_start - 1]}–{m[self.s2_end - 1]}"
        )


DEFAULT_BOUNDARIES = SemesterBoundaries(9, 12, 1, 6)


def rollover_due(school_year: str, today: date) -> bool:
    """Чи час пропонувати перехід класу з цього навчального року на наступний.

    З 1 серпня другого календарного року навчального року (рішення автора).
    """
    second_year = int(school_year[:4]) + 1
    return today >= date(second_year, ROLLOVER_MONTH, 1)


def next_school_year(school_year: str) -> str:
    first = int(school_year[:4]) + 1
    return f"{first}-{first + 1}"

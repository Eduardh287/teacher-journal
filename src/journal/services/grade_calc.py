"""Обчислення тематичних, семестрових і річних оцінок (етап 6, docs/specs/stage-6.md §0 K–L, §2).

Чисті функції без БД. Округлення — цілочисельне «half up» (7,5 → 8), без float.
«н/а» — лише позначка: в усіх розрахунках н/а = 0; обчислене 0 показується як «н/а».
"""
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Calc:
    """Результат обчислення: value=None означає «н/а»; total/count — складові середнього."""

    value: int | None
    total: int
    count: int

    @property
    def is_na(self) -> bool:
        return self.value is None


def half_up_mean(total: int, count: int) -> int:
    """Середнє total/count, округлене half up: (2·сума + n) // (2·n)."""
    if count <= 0:
        return 0
    return (2 * total + count) // (2 * count)


def _calc(total: int, count: int) -> Calc:
    mean = half_up_mean(total, count)
    return Calc(mean if mean > 0 else None, total, count)


def thematic(grades: Sequence[int]) -> Calc:
    """Тематична: середнє всіх оцінок періоду; без оцінок — н/а."""
    if not grades:
        return Calc(None, 0, 0)
    return _calc(sum(grades), len(grades))


def semester(thematic_values: Sequence[int | None]) -> Calc:
    """Семестрова: середнє по ВСІХ тематичних семестру (None/н/а = 0); без тематичних — н/а."""
    if not thematic_values:
        return Calc(None, 0, 0)
    return _calc(sum(v or 0 for v in thematic_values), len(thematic_values))


def annual(semester_1: int | None, semester_2: int | None) -> Calc:
    """Річна: (с1 + с2) / 2, відсутня чи н/а семестрова = 0; обидві н/а — н/а."""
    return _calc((semester_1 or 0) + (semester_2 or 0), 2)

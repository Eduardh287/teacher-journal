"""Тести чистих обчислень оцінок (services/grade_calc.py): half up, н/а = 0."""
import pytest

from journal.services import grade_calc as gc


@pytest.mark.parametrize(
    "total, count, expected",
    [(15, 2, 8), (7, 1, 7), (3, 2, 2), (14, 4, 4), (13, 4, 3), (10, 3, 3), (11, 3, 4), (0, 3, 0), (5, 0, 0)],
)
def test_half_up_mean(total, count, expected):
    assert gc.half_up_mean(total, count) == expected  # 7,5 → 8; 3,25 → 3; 3,67 → 4


def test_thematic_rounds_half_up_and_keeps_components():
    calc = gc.thematic([7, 8])
    assert (calc.value, calc.total, calc.count, calc.is_na) == (8, 15, 2, False)


def test_thematic_without_grades_is_na():
    assert gc.thematic([]) == gc.Calc(None, 0, 0)
    assert gc.thematic([]).is_na


def test_semester_counts_na_as_zero():
    """Тематичні н/а, 8, 10 → (0 + 8 + 10) / 3 = 6."""
    calc = gc.semester([None, 8, 10])
    assert (calc.value, calc.total, calc.count) == (6, 18, 3)


def test_semester_without_thematics_is_na():
    assert gc.semester([]).is_na


def test_semester_all_na_is_na_not_zero():
    calc = gc.semester([None, None])
    assert calc.is_na and calc.value is None and calc.count == 2


@pytest.mark.parametrize(
    "s1, s2, expected",
    [(8, 10, 9), (8, None, 4), (9, None, 5), (None, 9, 5), (None, None, None), (12, 12, 12), (1, None, 1)],
)
def test_annual(s1, s2, expected):
    """8 і 10 → 9; 8 і н/а → 4; 9 і н/а → 5 (4,5 → 5); обидві н/а → н/а."""
    assert gc.annual(s1, s2).value == expected

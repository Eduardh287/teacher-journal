"""Тести меж семестрів (чисті функції) і міграції c12d062be128."""
from datetime import date

import pytest
from sqlalchemy import text

from journal.services.semesters import (
    DEFAULT_BOUNDARIES,
    SemesterBoundaries,
    SemesterError,
    VacationDateError,
    rollover_due,
)

B = SemesterBoundaries


def test_defaults():
    assert DEFAULT_BOUNDARIES.validate() is DEFAULT_BOUNDARIES
    assert [DEFAULT_BOUNDARIES.semester_of_month(m) for m in range(1, 13)] == [
        2, 2, 2, 2, 2, 2, None, None, 1, 1, 1, 1,
    ]


def test_semester_for_vacation_raises():
    with pytest.raises(VacationDateError):
        DEFAULT_BOUNDARIES.semester_for(date(2027, 7, 15))


def test_wrapped_range_valid():
    b = B(8, 11, 2, 5).validate()  # I: серпень-листопад, II: лютий-травень
    assert b.semester_of_month(12) is None and b.semester_of_month(1) is None
    assert b.semester_of_month(2) == 2 and b.semester_of_month(8) == 1


@pytest.mark.parametrize(
    "b",
    [
        B(9, 12, 12, 6),   # перетин
        B(9, 12, 6, 1),    # II закінчується раніше, ніж починається (обгортка)
        B(1, 6, 9, 12),    # I семестр починається раніше за серпень
        B(9, 12, 1, 8),    # II закінчується не до серпня
        B(9, 12, 1, 13),   # місяць поза 1..12
        B(0, 12, 1, 6),
    ],
)
def test_invalid_boundaries_rejected(b):
    with pytest.raises(SemesterError):
        b.validate()


def test_contains_and_calendar_year():
    b = DEFAULT_BOUNDARIES
    assert b.contains("2026-2027", date(2026, 9, 1))
    assert b.contains("2026-2027", date(2027, 6, 30))
    assert not b.contains("2026-2027", date(2027, 9, 1))   # інший рік
    assert not b.contains("2026-2027", date(2027, 7, 1))   # канікули
    assert not b.contains("2026-2027", date(2026, 1, 10))  # січень попереднього року
    assert b.calendar_year("2026-2027", 12) == 2026 and b.calendar_year("2026-2027", 1) == 2027
    custom = B(8, 12, 1, 5)
    assert custom.contains("2026-2027", date(2026, 8, 20))


def test_rollover_due_edges():
    assert not rollover_due("2026-2027", date(2027, 7, 31))
    assert rollover_due("2026-2027", date(2027, 8, 1))
    assert rollover_due("2026-2027", date(2030, 1, 1))
    assert not rollover_due("2026-2027", date(2026, 9, 1))


def test_boundaries_label():
    assert DEFAULT_BOUNDARIES.label() == "I: вересень–грудень · II: січень–червень"


def test_schema_has_boundary_columns_and_checks(engine):
    """Міграція c12d062be128 застосована: стовпці з типовими значеннями й CHECK-обмеження.

    Сам downgrade/upgrade не входить у набір тестів: він блокує таблиці спільної бази journal_test
    (його перевіряють окремим скриптом на час релізу етапу).
    """
    with engine.connect() as conn:
        defaults = {
            (t, c): d
            for t, c, d in conn.execute(
                text(
                    "SELECT table_name, column_name, column_default FROM information_schema.columns "
                    "WHERE column_name IN ('s1_start_month', 's1_end_month', 's2_start_month', 's2_end_month') "
                    "AND table_name IN ('teachers', 'journals')"
                )
            )
        }
        checks = {
            r[0]
            for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_%_month'"))
        }
    expected = {"s1_start_month": "9", "s1_end_month": "12", "s2_start_month": "1", "s2_end_month": "6"}
    for table in ("teachers", "journals"):
        for column, default in expected.items():
            assert defaults[(table, column)].startswith(f"'{default}'")
            assert f"ck_{table}_{column}" in checks

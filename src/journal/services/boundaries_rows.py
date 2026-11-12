"""Читання/запис меж семестрів у рядках викладача (глобальні) і журналу (знімок).

Тут, а не в репозиторії: репозиторії не залежать від шару сервісів (рецензія Fable, PR #11).
"""
from journal.models import Journal, Teacher
from journal.services.semesters import SemesterBoundaries


def boundaries_of(row: Teacher | Journal) -> SemesterBoundaries:
    """Межі семестрів з рядка викладача (глобальні) або журналу (знімок)."""
    return SemesterBoundaries(
        row.s1_start_month, row.s1_end_month, row.s2_start_month, row.s2_end_month
    )


def set_boundaries(row: Teacher | Journal, boundaries: SemesterBoundaries) -> None:
    row.s1_start_month = boundaries.s1_start
    row.s1_end_month = boundaries.s1_end
    row.s2_start_month = boundaries.s2_start
    row.s2_end_month = boundaries.s2_end

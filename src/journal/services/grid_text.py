"""Тексти таблиці журналу, спільні для екрана й експорту в Excel: клітинки, назви й скорочення стовпців.

Тут немає Qt: цим користуються і ui/journal_grid.py, і services/export_service.py,
щоб експорт показував рівно те саме, що бачить викладачка в застосунку.
"""
from journal.services.journal_types import CellInfo, ComputedCell

NA_TEXT = "н/а"

# Тип уроку: код -> (назва, скорочення в заголовку стовпця)
LESSON_TYPES: dict[str, tuple[str, str]] = {
    "regular": ("Звичайний урок", ""),
    "test": ("Контрольна робота", "КР"),
    "lab": ("Лабораторна робота", "ЛР"),
    "independent": ("Самостійна робота", "СР"),
    "quiz": ("Тест", "Т"),  # етап 6, відгук викладачки
    "project": ("Проєкт", "Пр"),
}

# Стовпчики без дати (етап 6): назва, скорочення в заголовку (погоджено з викладачкою).
EXTRA_COLUMN_TYPES: dict[str, tuple[str, str]] = {
    "thematic": ("Тематична", "Тем"),
    "notebook": ("Зошит", "Зош"),
}
FINAL_COLUMN_TITLES: dict[str, tuple[str, str]] = {
    "semester": ("Семестрова", "Сем."),
    "annual": ("Річна", "Річна"),
}


def cell_text(cell: CellInfo) -> str:
    """Текст клітинки: н / хв / з / «з 9» / оцінка."""
    if cell.attendance == "absent":
        return "н"
    if cell.attendance == "sick":
        return "хв"
    if cell.attendance == "late":
        return f"з {cell.grade}" if cell.grade is not None else "з"
    return str(cell.grade) if cell.grade is not None else ""


def computed_text(kind: str, cell: ComputedCell | None) -> str:
    """Текст обчислюваної клітинки: оцінка або «н/а» (порожньо, якщо нічого немає)."""
    if cell is None:
        return ""
    if kind == "notebook":
        return str(cell.value) if cell.value is not None else ""
    if cell.is_na:
        return NA_TEXT
    return str(cell.value) if cell.value is not None else ""

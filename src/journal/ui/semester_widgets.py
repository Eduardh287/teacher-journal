"""Віджети налаштування семестрів: редактор меж і текст конфліктів зі зміною меж."""
from collections.abc import Sequence

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from journal.services.semesters import MONTHS_UA, SemesterBoundaries
from journal.ui.widgets import label

CONFLICT_LIMIT = 10  # скільки конфліктних уроків перелічуємо, далі «і ще N»
CONFLICT_HEADER = "Зміну не збережено: ці уроки потрапляють у канікули."


def conflict_text(conflicts: Sequence, header: str = CONFLICT_HEADER) -> str:
    """`header` і перелік уроків «9-А · Алгебра — 15.01.2027», що потрапляють у канікули (перші 10, далі «і ще N»)."""
    lines = [
        f"{c.class_name} · {c.subject_name} — {c.lesson_date:%d.%m.%Y}" for c in conflicts[:CONFLICT_LIMIT]
    ]
    if len(conflicts) > CONFLICT_LIMIT:
        lines.append(f"і ще {len(conflicts) - CONFLICT_LIMIT}")
    return "\n".join([header, *lines])


class SemesterBoundsEditor(QWidget):
    """Межі двох семестрів: рядки «I семестр: з [місяць] по [місяць]». `combos` — за ключами s1_start…s2_end."""

    KEYS = ("s1_start", "s1_end", "s2_start", "s2_end")

    def __init__(
        self, boundaries: SemesterBoundaries | None = None, *, caption_width: int = 0, spacing: int = 12
    ) -> None:
        super().__init__()
        self.combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        for caption, start_key, end_key in (("I семестр", "s1_start", "s1_end"), ("II семестр", "s2_start", "s2_end")):
            row = QHBoxLayout()
            row.setSpacing(8)
            if caption_width:  # підпис фіксованої ширини, «з» окремо — стовпці вирівняні між рядками
                title = label(f"{caption}:")
                title.setMinimumWidth(caption_width)
                row.addWidget(title)
                row.addWidget(label("з"))
            else:
                row.addWidget(label(f"{caption}: з"))
            row.addWidget(self._month_combo(start_key))
            row.addWidget(label("по"))
            row.addWidget(self._month_combo(end_key))
            row.addStretch(1)
            layout.addLayout(row)
        if boundaries is not None:
            self.set_boundaries(boundaries)

    def _month_combo(self, key: str) -> QComboBox:
        combo = QComboBox()
        for number, name in enumerate(MONTHS_UA, start=1):
            combo.addItem(name, number)
        self.combos[key] = combo
        return combo

    def boundaries(self) -> SemesterBoundaries:
        return SemesterBoundaries(*(self.combos[key].currentData() for key in self.KEYS))

    def set_boundaries(self, value: SemesterBoundaries) -> None:
        for key, month in zip(self.KEYS, (value.s1_start, value.s1_end, value.s2_start, value.s2_end)):
            self.combos[key].setCurrentIndex(month - 1)

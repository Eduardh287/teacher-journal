"""Картки сторінки «Налаштування»: межі семестрів і довідник предметів (етап 5.2)."""
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager

from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from journal.services.journal_types import JournalError, SemesterConflict
from journal.services.semesters import (
    DEFAULT_BOUNDARIES,
    MONTHS_UA,
    SemesterBoundaries,
    SemesterError,
)
from journal.services.subject_service import MAX_SUBJECT_NAME, SubjectError
from journal.ui.widgets import button, label

MAX_CONFLICTS_SHOWN = 10
GENERIC_ERROR = "Не вдалося зберегти зміни"


@contextmanager
def _default_settings_service():
    from journal.db import session_scope
    from journal.services.settings_service import SettingsService

    with session_scope() as session:
        yield SettingsService(session)


@contextmanager
def _default_subject_service():
    from journal.db import session_scope
    from journal.services.subject_service import SubjectService

    with session_scope() as session:
        yield SubjectService(session)


def _error_label() -> QLabel:
    widget = QLabel()
    widget.setProperty("error", True)
    widget.setWordWrap(True)
    widget.hide()
    return widget


def _month_combo() -> QComboBox:
    combo = QComboBox()
    for number, name in enumerate(MONTHS_UA, start=1):
        combo.addItem(name, number)
    return combo


def format_conflicts(conflicts) -> str:
    """«9-А · Алгебра — 15.01.2027», не більше 10 рядків, далі «і ще N»."""
    lines = [
        f"{c.class_name} · {c.subject_name} — {c.lesson_date:%d.%m.%Y}"
        for c in conflicts[:MAX_CONFLICTS_SHOWN]
    ]
    rest = len(conflicts) - MAX_CONFLICTS_SHOWN
    if rest > 0:
        lines.append(f"і ще {rest}")
    return "\n".join(lines)


class SemestersCard(QFrame):
    """Межі семестрів по місяцях; зберігаються одразу для всіх журналів у роботі."""

    def __init__(
        self,
        teacher_id: int,
        service_factory: Callable[[], AbstractContextManager] | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.teacher_id = teacher_id
        self._factory = service_factory or _default_settings_service
        self._on_saved = on_saved
        self._loaded = DEFAULT_BOUNDARIES

        self.setObjectName("Card")
        self._build()
        self.load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("Семестри", object_name="CardTitle"))
        layout.addWidget(label("Межі семестрів задаються місяцями. Інші місяці — канікули.", muted=True))

        self.s1_start, self.s1_end = _month_combo(), _month_combo()
        self.s2_start, self.s2_end = _month_combo(), _month_combo()
        layout.addLayout(self._row("I семестр:", self.s1_start, self.s1_end))
        layout.addLayout(self._row("II семестр:", self.s2_start, self.s2_end))

        actions = QHBoxLayout()
        self.save_button = button("Зберегти", variant="primary")
        self.save_button.clicked.connect(self._on_save)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status = label("", muted=True, wrap=True)
        self.status.hide()
        layout.addWidget(self.status)
        self.error = _error_label()
        layout.addWidget(self.error)

    @staticmethod
    def _row(title: str, start: QComboBox, end: QComboBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        caption = label(title)
        caption.setMinimumWidth(72)
        row.addWidget(caption)
        row.addWidget(label("з"))
        row.addWidget(start)
        row.addWidget(label("по"))
        row.addWidget(end)
        row.addStretch(1)
        return row

    # ---------- Дані ----------

    def _set_combos(self, b: SemesterBoundaries) -> None:
        for combo, month in (
            (self.s1_start, b.s1_start),
            (self.s1_end, b.s1_end),
            (self.s2_start, b.s2_start),
            (self.s2_end, b.s2_end),
        ):
            combo.setCurrentIndex(combo.findData(month))

    def boundaries(self) -> SemesterBoundaries:
        return SemesterBoundaries(
            self.s1_start.currentData(),
            self.s1_end.currentData(),
            self.s2_start.currentData(),
            self.s2_end.currentData(),
        )

    def load(self) -> None:
        try:
            with self._factory() as service:
                loaded = service.get_semesters(self.teacher_id)
        except Exception:
            logging.exception("Не вдалося завантажити межі семестрів")
            self._show_error("Не вдалося завантажити налаштування семестрів")
            return
        self._loaded = loaded
        self._set_combos(loaded)

    def _show_error(self, text: str) -> None:
        self.status.hide()
        self.error.setText(text)
        self.error.show()

    def _on_save(self) -> None:
        chosen = self.boundaries()
        try:
            with self._factory() as service:
                updated = service.set_semesters(self.teacher_id, chosen)
        except SemesterError as error:
            self._show_error(str(error))
            return
        except SemesterConflict as error:
            self._set_combos(self._loaded)
            self._show_error(f"{error}:\n{format_conflicts(error.conflicts)}")
            return
        except JournalError as error:
            self._show_error(str(error))
            return
        except Exception:
            logging.exception("Не вдалося зберегти межі семестрів")
            self._show_error(GENERIC_ERROR)
            return
        self._loaded = chosen
        self.error.hide()
        self.status.setText(f"Збережено. Оновлено журналів: {updated}")
        self.status.show()
        if self._on_saved is not None:
            self._on_saved()


class SubjectsCard(QFrame):
    """Список предметів і додавання власного (рішення автора)."""

    def __init__(
        self,
        service_factory: Callable[[], AbstractContextManager] | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._factory = service_factory or _default_subject_service
        self._on_changed = on_changed

        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("Предмети", object_name="CardTitle"))
        layout.addWidget(
            label("Предмети, для яких можна створювати журнали. Додайте свій, якщо його немає.", muted=True)
        )
        self.subjects_label = label("", wrap=True)
        layout.addWidget(self.subjects_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("Назва предмета, напр. Астрономія")
        self.subject_edit.setMaxLength(MAX_SUBJECT_NAME)
        self.subject_edit.returnPressed.connect(self._on_add)
        add = button("Додати", variant="primary")
        add.clicked.connect(self._on_add)
        row.addWidget(self.subject_edit, 1)
        row.addWidget(add)
        layout.addLayout(row)

        self.subject_error = _error_label()
        layout.addWidget(self.subject_error)
        self.load()

    def load(self) -> None:
        try:
            with self._factory() as service:
                subjects = service.list_subjects()
        except Exception:
            logging.exception("Не вдалося завантажити предмети")
            self.subjects_label.setText("Не вдалося завантажити список предметів")
            return
        self.subjects_label.setText(" · ".join(s.name for s in subjects))

    def _on_add(self) -> None:
        try:
            with self._factory() as service:
                service.add_subject(self.subject_edit.text())
        except SubjectError as error:
            self.subject_error.setText(str(error))
            self.subject_error.show()
            return
        except Exception:
            logging.exception("Не вдалося додати предмет")
            self.subject_error.setText(GENERIC_ERROR)
            self.subject_error.show()
            return
        self.subject_error.hide()
        self.subject_edit.clear()
        self.load()
        if self._on_changed is not None:
            self._on_changed()

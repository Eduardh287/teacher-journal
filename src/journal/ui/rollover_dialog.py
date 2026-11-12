"""Перехід на новий навчальний рік: вікно підтвердження і запуск після відкриття головного вікна.

UI працює з RolloverService лише через service_factory (за замовчуванням — окрема транзакція
journal.db.session_scope()). Специфікація: docs/specs/stage-5.2.md.
"""
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from typing import Any, Protocol

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from journal.db import session_scope
from journal.services.rollover_service import RolloverItem
from journal.ui.widgets import button, label

ERROR_TEXT = "Не вдалося виконати перехід на новий навчальний рік. Спробуйте пізніше."
COPY_TEXT = "Створити такі самі журнали для нових класів"


class RolloverApi(Protocol):
    def plan(self, teacher_id: int, today: date) -> list[RolloverItem]: ...

    def apply(self, teacher_id: int, today: date, copy_journals: bool = False) -> list[RolloverItem]: ...


ServiceFactory = Callable[[], AbstractContextManager[RolloverApi]]


@contextmanager
def default_service_factory():
    """Відкриває транзакцію й віддає сервіс переходу (імпорт відкладений)."""
    from journal.services.rollover_service import RolloverService

    with session_scope() as session:
        yield RolloverService(session)


def item_text(item: RolloverItem) -> str:
    """«9-А → 10-А (2027-2028), учнів: 28», «9-Б → архів (10-Б уже існує)», «11-Б → архів»."""
    if item.action == "promote":
        if item.target_exists:
            return f"{item.class_name} → архів ({item.new_name} уже існує)"
        return f"{item.class_name} → {item.new_name} ({item.new_year}), учнів: {item.student_count}"
    return f"{item.class_name} → архів"


class RolloverDialog(QDialog):
    """«Навчальний рік завершено»: перелік змін, галочка про журнали, «Гаразд» / «Пізніше»."""

    def __init__(self, items: list[RolloverItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items = items
        self.setWindowTitle("Навчальний рік завершено")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(label("Навчальний рік завершено", object_name="EmptyTitle"))
        layout.addWidget(label("Пропонується перейти на новий навчальний рік:", muted=True, wrap=True))
        self.lines = [label(item_text(item), wrap=True) for item in items]
        for line in self.lines:
            layout.addWidget(line)
        layout.addWidget(
            label("Старі класи разом із журналами й оцінками буде збережено в архіві без змін.", muted=True, wrap=True)
        )

        self.copy_check = QCheckBox(COPY_TEXT)
        self.copy_check.setChecked(False)
        has_subjects = any(i.action == "promote" and i.subject_names for i in items)
        self.copy_check.setVisible(has_subjects)
        layout.addWidget(self.copy_check)

        row = QHBoxLayout()
        self.later_button = button("Пізніше")
        self.later_button.clicked.connect(self.reject)
        self.ok_button = button("Гаразд", variant="primary")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.later_button)
        row.addWidget(self.ok_button)
        layout.addLayout(row)

    @property
    def copy_journals(self) -> bool:
        return self.copy_check.isVisibleTo(self) and self.copy_check.isChecked()


def maybe_run_rollover(
    window: Any,
    teacher_id: int,
    today: date | None = None,
    service_factory: ServiceFactory | None = None,
    dialog_factory: Callable[[list[RolloverItem], QWidget], QDialog] = RolloverDialog,
) -> bool:
    """Пропонує перехід на новий рік, якщо він потрібен. Повертає True, якщо перехід виконано."""
    today = today or date.today()
    factory = service_factory or default_service_factory
    try:
        with factory() as service:
            items = service.plan(teacher_id, today)
    except Exception:
        logging.exception("Не вдалося підготувати перехід на новий навчальний рік")
        return False
    if not items:
        return False
    parent = window if isinstance(window, QWidget) else None
    dialog = dialog_factory(items, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    copy_journals = bool(getattr(dialog, "copy_journals", False))
    try:
        with factory() as service:
            service.apply(teacher_id, today, copy_journals=copy_journals)
    except Exception:
        logging.exception("Помилка під час переходу на новий навчальний рік")
        QMessageBox.warning(parent, "Не вдалося виконати дію", ERROR_TEXT)
        return False
    _refresh_pages(window)
    return True


def _refresh_pages(window: Any) -> None:
    classes_page = getattr(window, "classes_page", None)
    if classes_page is not None:
        refresh = getattr(classes_page, "refresh", None) or getattr(classes_page, "show_list", None)
        if refresh is not None:
            refresh()
    journals_page = getattr(window, "journals_page", None)
    if journals_page is not None:
        journals_page.refresh()

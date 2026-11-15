"""Перехід на новий навчальний рік: вікно підтвердження і запуск після відкриття головного вікна.

UI працює з RolloverService лише через service_factory (за замовчуванням — окрема транзакція
ui.service_scope). Специфікація: docs/specs/stage-5.2.md.
"""
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import partial
from datetime import date
from typing import Any, Protocol

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QMessageBox, QWidget

from journal.services.grid_text import plural
from journal.services.rollover_service import RolloverItem, RolloverService
from journal.ui.service_scope import service_scope
from journal.ui.widgets import FormDialog, button, label

ERROR_TEXT = "Не вдалося виконати перехід на новий навчальний рік. Спробуйте пізніше."
COPY_TEXT = "Створити такі самі журнали для нових класів"


class RolloverApi(Protocol):
    def plan(self, teacher_id: int, today: date) -> list[RolloverItem]: ...

    def apply(self, teacher_id: int, today: date, copy_journals: bool = False) -> list[RolloverItem]: ...


ServiceFactory = Callable[[], AbstractContextManager[RolloverApi]]


def item_text(item: RolloverItem) -> str:
    """«9-А → 10-А (2027-2028), учнів: 28», «9-Б → архів (10-Б уже існує)», «11-Б → архів»;
    за пропущені роки: «9-А (2024-2025) → 11-А (2026-2027) · пропущено 1 рік»."""
    skipped = getattr(item, "years_skipped", 0)
    if item.action == "promote" and skipped > 0 and not item.target_exists:
        return (
            f"{item.class_name} ({item.school_year}) → {item.new_name} ({item.new_year})"
            f" · пропущено {skipped} {plural(skipped, 'рік', 'роки', 'років')}"
        )
    if item.action == "promote":
        if item.target_exists:
            return f"{item.class_name} → архів ({item.new_name} уже існує)"
        return f"{item.class_name} → {item.new_name} ({item.new_year}), учнів: {item.student_count}"
    return f"{item.class_name} → архів"


class RolloverDialog(FormDialog):
    """«Навчальний рік завершено»: перелік змін, галочка про журнали, «Гаразд» / «Пізніше»."""

    def __init__(self, items: list[RolloverItem], parent: QWidget | None = None) -> None:
        super().__init__("Навчальний рік завершено", parent, width=480)
        self.items = items
        layout = self.body
        layout.addWidget(label("Пропонується перейти на новий навчальний рік:", muted=True, wrap=True))
        self.lines = [label(item_text(item), wrap=True) for item in items]
        for line in self.lines:
            layout.addWidget(line)
        self.catch_up_note = None
        if any(getattr(i, "years_skipped", 0) > 0 for i in items):
            self.catch_up_note = label(
                "За пропущені роки буде створено порожні класи в архіві (без учнів і журналів).",
                muted=True,
                wrap=True,
            )
            layout.addWidget(self.catch_up_note)
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
    factory = service_factory or partial(service_scope, RolloverService)
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

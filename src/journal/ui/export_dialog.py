"""Експорт журналу в Excel: діалог періоду, вибір файлу, повідомлення «Файл збережено» (специфікація excel-export).

UI працює лише з JournalApi та DTO сервісів; побудова таблиці й запис файлу — у services/.
Функції ask_period / choose_save_path / show_saved / show_failure / show_notice винесено окремо,
щоб тести підміняли їх (без справжніх вікон і файлових діалогів).
"""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QStandardPaths
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from journal.services.export_service import (
    BAD_RANGE_TEXT,
    PRESET_CURRENT,
    PRESET_NAMES,
    ExportError,
    ExportTable,
    build_export_table,
    period_presets,
    suggest_file_name,
)
from journal.services.journal_types import JournalApi, JournalError, JournalInfo
from journal.logging_setup import log_failure
from journal.ui import theme
from journal.ui.settings_cards import open_folder
from journal.ui.widgets import button, field, label

EXPORT_DIR_KEY = "export_dir"
CUSTOM_PERIOD = "Власний період"
GENERIC_EXPORT_ERROR = "Не вдалося створити файл. Спробуйте ще раз."
ApiFactory = Callable[[], AbstractContextManager[JournalApi]]


class ExportDialog(QDialog):
    """Вибір періоду: швидкі варіанти й дві дати «з» / «по»."""

    def __init__(self, info: JournalInfo, parent: QWidget | None = None, today: date | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Експорт в Excel")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._presets = period_presets(info, today or date.today())

        body = QVBoxLayout(self)
        body.setContentsMargins(32, 28, 32, 28)
        body.setSpacing(14)
        body.addWidget(label("Експорт в Excel", object_name="EmptyTitle"))
        body.addWidget(label(f"{info.class_name} · {info.subject_name}", muted=True))

        self.preset_combo = QComboBox()
        for name in PRESET_NAMES:
            self.preset_combo.addItem(name)
        self.preset_combo.addItem(CUSTOM_PERIOD)
        body.addWidget(field("ПЕРІОД", self.preset_combo))

        self.from_edit = self._date_edit()
        self.to_edit = self._date_edit()
        dates = QHBoxLayout()
        dates.setSpacing(12)
        dates.addWidget(field("З", self.from_edit))
        dates.addWidget(field("ПО", self.to_edit))
        body.addLayout(dates)

        self.error_label = label("", wrap=True)
        self.error_label.setProperty("error", True)
        self.error_label.hide()
        body.addWidget(self.error_label)

        self.submit_button = button("Далі", variant="primary")
        self.submit_button.setMinimumHeight(40)
        self.submit_button.setDefault(True)
        self.submit_button.clicked.connect(self._on_submit)
        cancel = button("Скасувати")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.submit_button)
        body.addLayout(buttons)

        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        self.from_edit.dateChanged.connect(self._on_date_edited)
        self.to_edit.dateChanged.connect(self._on_date_edited)
        self.set_preset(PRESET_CURRENT)

    @staticmethod
    def _date_edit() -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setMinimumDate(QDate(2000, 1, 1))
        return edit

    def set_preset(self, name: str) -> None:
        self.preset_combo.setCurrentIndex(self.preset_combo.findText(name))
        self._on_preset()  # сигнал не спрацює, якщо варіант уже вибрано

    def _on_preset(self) -> None:
        period = self._presets.get(self.preset_combo.currentText())
        if period is None:
            return  # «Власний період» — дати лишаються як є
        for edit, day in ((self.from_edit, period[0]), (self.to_edit, period[1])):
            edit.blockSignals(True)
            edit.setDate(day)
            edit.blockSignals(False)
        self.error_label.hide()

    def _on_date_edited(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(self.preset_combo.findText(CUSTOM_PERIOD))
        self.preset_combo.blockSignals(False)
        self.error_label.hide()

    def period(self) -> tuple[date, date]:
        return self.from_edit.date().toPython(), self.to_edit.date().toPython()

    def _on_submit(self) -> None:
        start, end = self.period()
        if start > end:
            self.error_label.setText(BAD_RANGE_TEXT)
            self.error_label.show()
            return
        self.accept()


# ---------- діалоги, які підміняють тести ----------


def ask_period(parent: QWidget | None, info: JournalInfo) -> tuple[date, date] | None:
    dialog = ExportDialog(info, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.period()


def default_export_dir() -> str:
    """Остання папка експорту (QSettings) або «Документи»."""
    saved = theme.app_settings().value(EXPORT_DIR_KEY, "")
    if saved and Path(str(saved)).is_dir():
        return str(saved)
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())


def choose_save_path(parent: QWidget | None, file_name: str) -> Path | None:
    """Діалог «Зберегти як…». Запам'ятовує папку; повертає шлях із розширенням .xlsx або None."""
    start = str(Path(default_export_dir()) / file_name)
    chosen, _filter = QFileDialog.getSaveFileName(parent, "Зберегти файл Excel", start, "Файли Excel (*.xlsx)")
    if not chosen:
        return None
    path = Path(chosen)
    if path.suffix.lower() != ".xlsx":
        path = path.with_name(path.name + ".xlsx")
    theme.app_settings().setValue(EXPORT_DIR_KEY, str(path.parent))
    return path


def build_saved_box(parent: QWidget | None, path: Path) -> tuple[QMessageBox, object]:
    box = QMessageBox(QMessageBox.Icon.Information, "Файл збережено", f"Файл збережено:\n{path}", parent=parent)
    open_button = box.addButton("Відкрити папку", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Готово", QMessageBox.ButtonRole.AcceptRole)
    return box, open_button


def show_saved(parent: QWidget | None, path: Path) -> None:
    box, open_btn = build_saved_box(parent, path)
    box.exec()
    if box.clickedButton() is open_btn:
        open_folder(path.parent)


def show_failure(parent: QWidget | None, text: str) -> None:
    QMessageBox.warning(parent, "Експорт не вдався", text)


def show_notice(parent: QWidget | None, text: str) -> None:
    QMessageBox.information(parent, "Експорт в Excel", text)


# ---------- сценарій ----------


def write_export(table: ExportTable, path: Path) -> Path:
    """Запис .xlsx; openpyxl вантажиться лише тут, щоб не сповільнювати запуск застосунку."""
    from journal.services.xlsx_writer import write_export as write

    return write(table, path)


def export_journal(parent: QWidget | None, api_factory: ApiFactory, teacher_id: int, info: JournalInfo) -> Path | None:
    """Період → таблиця → файл → «Файл збережено». Повертає шлях або None (скасовано / помилка)."""
    period = ask_period(parent, info)
    if period is None:
        return None
    start, end = period
    try:
        with api_factory() as api:
            table = build_export_table(api, teacher_id, info.id, start, end)
    except (ExportError, JournalError) as error:
        show_notice(parent, str(error))
        return None
    except Exception:
        log_failure("Помилка під час підготовки експорту")
        show_failure(parent, GENERIC_EXPORT_ERROR)
        return None
    path = choose_save_path(parent, suggest_file_name(info, start, end))
    if path is None:
        return None
    try:
        write_export(table, path)
    except ExportError as error:
        show_failure(parent, str(error))
        return None
    except Exception:
        log_failure("Помилка під час запису файлу експорту")
        show_failure(parent, GENERIC_EXPORT_ERROR)
        return None
    show_saved(parent, path)
    return path

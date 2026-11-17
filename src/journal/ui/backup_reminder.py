"""Нагадування про резервну копію (правки викладачки 1, C).

Після входу й далі щогодини перевіряємо: чи минув обраний період від останньої копії
(будь-яка копія «створена вручну» в папці копій або копія з нагадування; автокопії при виході
не рахуються — вони лежать на тому самому комп'ютері). Якщо минув — пропонуємо зробити копію
в обрану папку (наприклад, на флешку).
"""
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from journal.logging_setup import log_failure
from journal.services.backup_service import BackupError, BackupService
from journal.ui import backup_dialogs
from journal.ui.theme import app_settings

DAYS_KEY = "backup_reminder_days"
LAST_KEY = "backup_reminder_last"
SNOOZE_KEY = "backup_reminder_snooze"
FOLDER_KEY = "backup_reminder_folder"

DEFAULT_DAYS = 7
PERIODS = ((0, "Не нагадувати"), (1, "Щодня"), (7, "Щотижня"), (30, "Щомісяця"))
CHECK_EVERY_MS = 60 * 60 * 1000


# ---------------------------------------------------------------- налаштування

def load_days() -> int:
    try:
        days = int(app_settings().value(DAYS_KEY, DEFAULT_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return days if days in dict(PERIODS) else DEFAULT_DAYS


def save_days(days: int) -> None:
    app_settings().setValue(DAYS_KEY, int(days))


def _load_time(key: str) -> datetime | None:
    value = app_settings().value(key, "")
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _save_time(key: str, moment: datetime) -> None:
    app_settings().setValue(key, moment.isoformat(timespec="seconds"))


# ---------------------------------------------------------------- чиста логіка

def last_copy_time(backups, remembered: datetime | None) -> datetime | None:
    """Найпізніша з: найновіша копія «manual» у папці та час останньої копії з нагадування."""
    times = [b.created for b in backups if b.kind == "manual"]
    if remembered is not None:
        times.append(remembered)
    return max(times) if times else None


def days_since(now: datetime, last: datetime) -> int:
    return max((now - last).days, 0)


def is_due(now: datetime, days: int, last: datetime | None, snooze_until: datetime | None) -> bool:
    """Чи пора нагадати. Без жодної копії (last=None) — не нагадуємо (годинник стартує окремо)."""
    if days <= 0 or last is None:
        return False
    if snooze_until is not None and now < snooze_until:
        return False
    return now - last >= timedelta(days=days)


def days_text(count: int) -> str:
    """«1 день», «3 дні», «7 днів» (українські відмінки)."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} день"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} дні"
    return f"{count} днів"


# ---------------------------------------------------------------- діалоги (у тестах підміняються)

def ask_reminder(parent: QWidget | None, count: int) -> bool:
    """True — «Зробити копію…», False — «Пізніше»."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Резервна копія")
    box.setText(f"Минуло {days_text(count)} від останньої резервної копії. Зробити копію зараз?")
    box.setInformativeText("Її можна зберегти, наприклад, на флешку.")
    yes = box.addButton("Зробити копію…", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Пізніше", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def pick_folder(parent: QWidget | None, start: str) -> str:
    return QFileDialog.getExistingDirectory(parent, "Куди зберегти резервну копію", start)


def show_done(parent: QWidget | None, path: Path) -> bool:
    """Повідомлення про успіх. True — натиснуто «Відкрити папку»."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Резервна копія")
    # Повний шлях: якщо обрана папка недоступна для запису, копія лягає в типову папку.
    box.setText(f"Копію створено:\n{path}")
    open_button = box.addButton("Відкрити папку", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Гаразд", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    return box.clickedButton() is open_button


# ---------------------------------------------------------------- керування

class BackupReminder(QObject):
    def __init__(self, window: QWidget, service_factory=None) -> None:
        super().__init__(window)
        self._window = window
        self._factory = service_factory or self._default_service
        self._busy = False  # одне нагадування за раз
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_EVERY_MS)
        self.timer.timeout.connect(self.check)

    @staticmethod
    def _default_service(folder: str | None) -> BackupService:
        return BackupService.for_app(folder)

    def start(self) -> None:
        self.check()
        self.timer.start()

    def check(self, now: datetime | None = None) -> None:
        if self._busy:
            return
        now = now or datetime.now()
        days = load_days()
        if days <= 0:
            return
        try:
            from journal.ui.settings_cards import load_backup_dir

            backups = self._factory(load_backup_dir()).list_backups()
        except Exception:
            log_failure("Нагадування про копію: не вдалося прочитати список копій")
            return
        last = last_copy_time(backups, _load_time(LAST_KEY))
        if last is None:  # перший запуск: годинник стартує зараз, не набридаємо одразу
            _save_time(LAST_KEY, now)
            return
        if not is_due(now, days, last, _load_time(SNOOZE_KEY)):
            return
        self._busy = True
        try:
            self._remind(now, days_since(now, last))
        finally:
            self._busy = False

    def _remind(self, now: datetime, count: int) -> None:
        if not ask_reminder(self._window, count):
            _save_time(SNOOZE_KEY, now + timedelta(days=1))
            return
        from journal.ui.settings_cards import load_backup_dir

        start = str(app_settings().value(FOLDER_KEY, "") or load_backup_dir() or "")
        folder = pick_folder(self._window, start)
        if not folder:  # передумала: нагадаємо завтра
            _save_time(SNOOZE_KEY, now + timedelta(days=1))
            return
        self._make_copy(folder, now)

    def _make_copy(self, folder: str, now: datetime) -> None:
        try:
            service = self._factory(folder)
            path = backup_dialogs.run_busy(
                self._window, "Створюю резервну копію…", lambda: service.create_backup("manual")
            )
        except BackupError as error:
            backup_dialogs.show_warning(self._window, "Резервна копія", str(error))
            return
        except Exception:
            log_failure("Нагадування про копію: не вдалося створити копію")
            backup_dialogs.show_warning(
                self._window, "Резервна копія", "Не вдалося створити резервну копію. Деталі — у журналі."
            )
            return
        _save_time(LAST_KEY, now)
        settings = app_settings()
        settings.setValue(FOLDER_KEY, folder)
        settings.remove(SNOOZE_KEY)
        if show_done(self._window, Path(path)):
            from journal.ui.settings_cards import open_folder

            open_folder(Path(path).parent)


def start_backup_reminder(window: QWidget) -> BackupReminder:
    """Викликати один раз після входу: перевіряє зараз і далі щогодини."""
    reminder = BackupReminder(window)
    reminder.start()
    return reminder

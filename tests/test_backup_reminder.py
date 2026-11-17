"""Нагадування про резервну копію: чиста логіка + керування (offscreen, фейковий сервіс, без діалогів)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до будь-якого імпорту Qt

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from journal.services.backup_service import BackupError, BackupInfo
from journal.ui import backup_dialogs, backup_reminder as br
from journal.ui.settings_cards import BackupsCard
from journal.ui.theme import app_settings
from tests.fakes.fake_backup import FakeBackupService

NOW = datetime(2026, 11, 20, 12, 0)


def info(created: datetime, kind: str) -> BackupInfo:
    return BackupInfo(Path(f"x_{kind}.dump"), created, kind)


# ---------------------------------------------------------------- чиста логіка

def test_last_copy_ignores_auto_and_takes_max():
    backups = [info(NOW, "auto"), info(NOW - timedelta(days=3), "manual"), info(NOW - timedelta(days=9), "manual")]
    assert br.last_copy_time(backups, None) == NOW - timedelta(days=3)
    assert br.last_copy_time(backups, NOW - timedelta(days=1)) == NOW - timedelta(days=1)
    assert br.last_copy_time(backups, NOW - timedelta(days=30)) == NOW - timedelta(days=3)
    assert br.last_copy_time([info(NOW, "auto")], None) is None


def test_is_due():
    last = NOW - timedelta(days=7)
    assert br.is_due(NOW, 7, last, None)
    assert not br.is_due(NOW, 7, NOW - timedelta(days=6), None)
    assert not br.is_due(NOW, 0, last, None)  # «Не нагадувати»
    assert not br.is_due(NOW, 7, None, None)  # копій ще не було
    assert not br.is_due(NOW, 7, last, NOW + timedelta(hours=1))  # відкладено
    assert br.is_due(NOW, 7, last, NOW - timedelta(hours=1))


@pytest.mark.parametrize(
    "count, text",
    [(1, "1 день"), (2, "2 дні"), (7, "7 днів"), (11, "11 днів"), (14, "14 днів"), (21, "21 день"), (30, "30 днів")],
)
def test_days_text(count, text):
    assert br.days_text(count) == text


def test_days_setting_default_and_roundtrip():
    assert br.load_days() == 7
    br.save_days(30)
    assert br.load_days() == 30
    app_settings().setValue(br.DAYS_KEY, "5")  # некоректне значення → типове
    assert br.load_days() == 7


# ---------------------------------------------------------------- керування

class Harness:
    def __init__(self, monkeypatch, qtbot, service):
        self.service = service
        self.asked: list[int] = []
        self.answer = False
        self.folder = "D:/флешка"
        self.starts: list[str] = []
        self.done: list[str] = []
        self.warnings: list[str] = []
        self.opened: list[Path] = []
        self.factory_folders: list = []
        window = QWidget()
        qtbot.addWidget(window)
        self.reminder = br.BackupReminder(window, self._factory)

        def ask(parent, count):
            self.asked.append(count)
            return self.answer

        def pick(parent, start):
            self.starts.append(start)
            return self.folder

        monkeypatch.setattr(br, "ask_reminder", ask)
        monkeypatch.setattr(br, "pick_folder", pick)
        monkeypatch.setattr(br, "show_done", lambda p, path: self.done.append(path.name) or True)
        monkeypatch.setattr(backup_dialogs, "run_busy", lambda parent, text, action: action())
        monkeypatch.setattr(backup_dialogs, "show_warning", lambda p, t, x: self.warnings.append(x))
        import journal.ui.settings_cards as cards

        monkeypatch.setattr(cards, "open_folder", lambda path: self.opened.append(path))

    def _factory(self, folder):
        self.factory_folders.append(folder)
        return self.service


@pytest.fixture
def harness(monkeypatch, qtbot):
    def make(*backups, **kw):
        return Harness(monkeypatch, qtbot, FakeBackupService(backups, **kw))

    return make


def old_manual(days=10):
    return info(NOW - timedelta(days=days), "manual")


def test_first_run_starts_clock_without_asking(harness):
    h = harness()
    h.reminder.check(NOW)
    assert h.asked == []
    assert br._load_time(br.LAST_KEY) == NOW
    h.reminder.check(NOW + timedelta(days=6))
    assert h.asked == []
    h.reminder.check(NOW + timedelta(days=7))
    assert h.asked == [7]


def test_disabled_never_asks(harness):
    br.save_days(0)
    h = harness(old_manual(100))
    h.reminder.check(NOW)
    assert h.asked == []


def test_recent_manual_copy_no_reminder_auto_ignored(harness):
    h = harness(info(NOW - timedelta(days=1), "manual"), info(NOW, "auto"))
    h.reminder.check(NOW)
    assert h.asked == []
    h = harness(info(NOW, "auto"), old_manual(10))
    h.reminder.check(NOW)
    assert h.asked == [10]


def test_later_snoozes_until_next_day(harness):
    h = harness(old_manual())
    h.reminder.check(NOW)
    h.reminder.check(NOW + timedelta(hours=23))
    assert h.asked == [10]
    h.reminder.check(NOW + timedelta(days=1))
    assert len(h.asked) == 2


def test_make_copy_success(harness):
    h = harness(old_manual(), folder=Path("D:/флешка"))
    h.answer = True
    app_settings().setValue(br.FOLDER_KEY, "E:/раніше")
    h.reminder.check(NOW)
    assert h.starts == ["E:/раніше"]  # починає з останньої папки для нагадувань
    assert h.factory_folders[-1] == "D:/флешка"
    assert h.service.created == ["manual"]
    assert h.done == ["journal_2026-11-14_10-00-00_manual.dump"]
    assert h.opened == [Path("D:/флешка")]
    assert br._load_time(br.LAST_KEY) == NOW
    assert app_settings().value(br.FOLDER_KEY) == "D:/флешка"


def test_start_folder_falls_back_to_backups_folder(harness):
    h = harness(old_manual())
    h.answer = True
    h.reminder.check(NOW)
    assert h.starts == [""]  # нічого не збережено → системний вибір


def test_cancelled_picker_snoozes(harness):
    h = harness(old_manual())
    h.answer = True
    h.folder = ""
    h.reminder.check(NOW)
    assert h.service.created == []
    h.reminder.check(NOW + timedelta(hours=1))
    assert len(h.asked) == 1


@pytest.mark.parametrize("error, shown", [(BackupError("Диск повний"), "Диск повний"), (RuntimeError("секрет"), "Деталі — у журналі")])
def test_failure_shows_message_and_keeps_due(harness, error, shown):
    h = harness(old_manual(), error=error)
    h.answer = True
    h.reminder.check(NOW)
    assert len(h.warnings) == 1 and shown in h.warnings[0]
    assert "секрет" not in h.warnings[0]
    assert h.done == []
    assert br._load_time(br.LAST_KEY) is None


def test_never_two_reminders_at_once(harness, monkeypatch):
    h = harness(old_manual())

    def ask_and_recheck(parent, count):
        h.asked.append(count)
        h.reminder.check(NOW)  # спрацював таймер, поки діалог відкритий
        return False

    monkeypatch.setattr(br, "ask_reminder", ask_and_recheck)
    h.reminder.check(NOW)
    assert h.asked == [10]


def test_start_backup_reminder_checks_and_runs_hourly(harness, monkeypatch, qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    monkeypatch.setattr(br, "load_days", lambda: 0)
    reminder = br.start_backup_reminder(window)
    assert reminder.timer.isActive() and reminder.timer.interval() == 3600 * 1000
    assert reminder.parent() is window


# ---------------------------------------------------------------- картка налаштувань

def test_card_period_selector(qtbot):
    card = BackupsCard(service_factory=lambda d: FakeBackupService(), get_dir=lambda: None, set_dir=lambda p: None)
    qtbot.addWidget(card)
    assert [b.text() for b in card.period_buttons.values()] == ["Не нагадувати", "Щодня", "Щотижня", "Щомісяця"]
    assert card.period_buttons[7].isChecked()
    card.period_buttons[30].click()
    assert br.load_days() == 30
    card.period_buttons[0].click()
    assert br.load_days() == 0

"""Картка «Резервні копії» (offscreen, на фейковому сервісі)."""
from datetime import datetime
from pathlib import Path

import pytest

from journal.services.backup_service import BackupError, BackupInfo, BackupTooNewError, RestoreFailed
from journal.ui import backup_dialogs, settings_cards, theme
from journal.ui.backup_dialogs import RestoreConfirmDialog
from journal.ui.settings_cards import BackupsCard
from tests.fakes.fake_backup import FakeBackupService


class Env:
    def __init__(self, service):
        self.service = service
        self.dir = None
        self.restored_calls = 0
        self.messages: list[tuple[str, str]] = []


@pytest.fixture
def make_card(qtbot, monkeypatch):
    def factory(service=None, confirm=True):
        env = Env(service or FakeBackupService())
        monkeypatch.setattr(backup_dialogs, "confirm_restore", lambda parent, info: confirm)
        monkeypatch.setattr(backup_dialogs, "show_info", lambda p, t, x: env.messages.append(("info", x)))
        monkeypatch.setattr(backup_dialogs, "show_warning", lambda p, t, x: env.messages.append(("warn", x)))
        card = BackupsCard(
            service_factory=lambda d: env.service,
            get_dir=lambda: env.dir,
            set_dir=lambda p: setattr(env, "dir", p),
            on_restored=lambda: setattr(env, "restored_calls", env.restored_calls + 1),
        )
        qtbot.addWidget(card)
        card.resize(900, 300)
        card.show()
        env.card = card
        return env

    return factory


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_card_renders_in_both_themes(make_card, qapp, theme_name):
    theme.apply_theme(qapp, theme_name)
    env = make_card()
    card = env.card
    assert card.latest_label.text() == "Копій ще немає"
    assert "копії" in card.folder_label.text()
    for button in (card.create_button, card.open_button, card.change_button, card.restore_button):
        assert button.isVisible() and button.isEnabled()
    assert [b.text() for b in (card.create_button, card.restore_button)] == [
        "Створити копію зараз", "Відновити з копії…"
    ]
    assert card.grab().width() > 0  # відмальовується без винятків


def test_shows_newest_backup(make_card):
    env = make_card(FakeBackupService([BackupInfo(Path("x"), datetime(2026, 11, 13, 18, 5), "auto")]))
    assert "13.11.2026 18:05" in env.card.latest_label.text()
    assert "автоматична" in env.card.latest_label.text()


def test_create_button_calls_service(make_card):
    env = make_card()
    env.card.create_button.click()
    assert env.service.created == ["manual"]
    assert "Копію створено" in env.card.status.text()
    assert "14.11.2026" in env.card.latest_label.text()


def test_create_error_is_shown(make_card):
    env = make_card(FakeBackupService(error=BackupError("Не вдалося створити резервну копію.")))
    env.card.create_button.click()
    assert env.card.error.isVisible()
    assert env.card.error.text() == "Не вдалося створити резервну копію."


def test_change_folder_saves_choice(make_card, monkeypatch):
    env = make_card()
    monkeypatch.setattr(settings_cards.QFileDialog, "getExistingDirectory", lambda *a, **k: "D:/Флешка")
    env.card.change_button.click()
    assert env.dir.replace("\\", "/") == "D:/Флешка"


def test_change_folder_cancel_keeps_setting(make_card, monkeypatch):
    env = make_card()
    monkeypatch.setattr(settings_cards.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    env.card.change_button.click()
    assert env.dir is None


def test_open_folder_button(make_card, monkeypatch):
    env = make_card()
    opened = []
    monkeypatch.setattr(settings_cards, "open_folder", opened.append)
    env.card.open_button.click()
    assert opened == [env.service.folder]


def pick(monkeypatch, name="C:/копії/journal_2026-11-01_09-30-00_auto.dump"):
    monkeypatch.setattr(settings_cards.QFileDialog, "getOpenFileName", lambda *a, **k: (name, ""))


def test_restore_flow_calls_service_and_closes_app(make_card, monkeypatch):
    env = make_card()
    pick(monkeypatch)
    env.card.restore_button.click()
    assert [p.name for p in env.service.restored] == ["journal_2026-11-01_09-30-00_auto.dump"]
    assert env.restored_calls == 1
    assert any("Програма закриється" in text for _, text in env.messages)


def test_restore_declined_does_nothing(make_card, monkeypatch):
    env = make_card(confirm=False)
    pick(monkeypatch)
    env.card.restore_button.click()
    assert env.service.restored == [] and env.restored_calls == 0


def test_restore_cancelled_file_dialog(make_card, monkeypatch):
    env = make_card()
    pick(monkeypatch, "")
    env.card.restore_button.click()
    assert env.service.restored == [] and env.restored_calls == 0


def test_restore_newer_copy_refused_before_confirm(make_card, monkeypatch):
    env = make_card(FakeBackupService(inspect_error=BackupTooNewError("Копію створено новішою версією програми.")))
    pick(monkeypatch)
    env.card.restore_button.click()
    assert "новішою версією" in env.card.error.text()
    assert env.service.restored == [] and env.restored_calls == 0


def test_restore_failure_reports_and_keeps_app_open(make_card, monkeypatch):
    env = make_card(FakeBackupService(restore_error=RestoreFailed("Нічого не змінено.", rolled_back=True)))
    pick(monkeypatch)
    env.card.restore_button.click()
    assert env.restored_calls == 0
    assert "Нічого не змінено" in env.card.error.text()
    assert env.messages and env.messages[0][0] == "warn"


def test_confirm_dialog_requires_typed_word(qtbot):
    info = BackupInfo(Path("x"), datetime(2026, 11, 1, 9, 30), "manual", "rev")
    dialog = RestoreConfirmDialog(info)
    qtbot.addWidget(dialog)
    assert not dialog.delete_button.isEnabled()
    dialog.confirm_edit.setText("видалити")
    assert not dialog.delete_button.isEnabled()
    dialog.confirm_edit.setText("Відновити")
    assert dialog.delete_button.isEnabled()
    assert dialog.delete_button.text() == "Відновити"


def test_fallback_note_follows_service_state(make_card):
    env = make_card()
    assert env.card.fallback_note.isHidden()
    env.service.fallback_used = True
    env.card.refresh()
    assert env.card.fallback_note.isVisible()
    assert env.card.fallback_note.text() == "Обрана папка недоступна — копії зберігаються в типовій"
    env.service.fallback_used = False
    env.card.refresh()
    assert env.card.fallback_note.isHidden()


class _Recoverable:
    def __init__(self, copy, error=None):
        self.copy = copy
        self.error = error
        self.recovered = []

    def interrupted_restore_copy(self):
        return self.copy

    def recover_interrupted_restore(self, copy):
        if self.error:
            raise self.error
        self.recovered.append(copy)


def _patch_messages(monkeypatch):
    messages = []
    monkeypatch.setattr(backup_dialogs, "show_info", lambda p, t, x: messages.append(("info", x)))
    monkeypatch.setattr(backup_dialogs, "show_warning", lambda p, t, x: messages.append(("warn", x)))
    monkeypatch.setattr(backup_dialogs, "run_busy", lambda parent, text, action: action())
    return messages


def test_startup_recovery_accepted(monkeypatch):
    messages = _patch_messages(monkeypatch)
    service = _Recoverable(Path("x.dump"))
    assert backup_dialogs.recover_interrupted_restore(lambda: service, ask=lambda p: True) is True
    assert service.recovered == [Path("x.dump")]
    assert "Відкрийте програму знову" in messages[0][1]


def test_startup_recovery_declined_or_absent(monkeypatch):
    _patch_messages(monkeypatch)
    declined = _Recoverable(Path("x.dump"))
    assert backup_dialogs.recover_interrupted_restore(lambda: declined, ask=lambda p: False) is False
    assert declined.recovered == []
    none = _Recoverable(None)
    assert backup_dialogs.recover_interrupted_restore(lambda: none, ask=lambda p: pytest.fail("no ask")) is False


def test_startup_recovery_failure_does_not_block_start(monkeypatch):
    messages = _patch_messages(monkeypatch)
    service = _Recoverable(Path("x.dump"), error=BackupError("Не вдалося повернути."))
    assert backup_dialogs.recover_interrupted_restore(lambda: service, ask=lambda p: True) is False
    assert messages[0][0] == "warn"


class _Unavailable(_Recoverable):
    restore_copy_unavailable = True


def test_unavailable_copy_folder_is_reported_once(monkeypatch):
    messages = _patch_messages(monkeypatch)
    service = _Unavailable(None)
    for _ in range(3):
        assert backup_dialogs.recover_interrupted_restore(lambda: service, ask=lambda p: pytest.fail("no ask")) is False
    assert [kind for kind, _ in messages] == ["warn"]
    assert "недоступна" in messages[0][1]
    # копія знову доступна -> прапорець скинуто, наступна недоступність знову повідомить
    backup_dialogs.recover_interrupted_restore(lambda: _Recoverable(None), ask=lambda p: False)
    backup_dialogs.recover_interrupted_restore(lambda: service, ask=lambda p: False)
    assert [kind for kind, _ in messages] == ["warn", "warn"]

"""Автокопія при закритті головного вікна (хук closeEvent)."""
from PySide6.QtWidgets import QWidget

from journal.services.auth_service import CurrentUser
from journal.ui import backup_dialogs
from journal.ui.main_window import MainWindow
from journal.ui.settings_cards import BackupsCard


def make_window(qtbot, monkeypatch, exit_backup):
    monkeypatch.setattr(BackupsCard, "refresh", lambda self: None)  # не читати справжню папку копій
    window = MainWindow(CurrentUser(1, "t", "Викладач"), exit_backup=exit_backup)
    qtbot.addWidget(window)
    return window


def test_close_runs_exit_backup_once(qtbot, monkeypatch):
    calls = []
    window = make_window(qtbot, monkeypatch, lambda parent: calls.append(parent))
    window.show()
    window.close()
    window.close()
    assert calls == [window]


def test_exit_backup_failure_does_not_block_close(qtbot, monkeypatch):
    def boom(parent):
        raise RuntimeError("disk full")

    window = make_window(qtbot, monkeypatch, boom)
    window.show()
    window.close()
    assert not window.isVisible()


def test_no_exit_backup_by_default(qtbot, monkeypatch):
    window = make_window(qtbot, monkeypatch, None)
    window.show()
    window.close()
    assert not window.isVisible()


def test_close_after_restore_skips_backup(qtbot, monkeypatch):
    calls = []
    window = make_window(qtbot, monkeypatch, lambda parent: calls.append(1))
    window.show()
    window._close_after_restore()
    assert calls == []


def test_default_exit_backup_warns_but_never_raises(qtbot, monkeypatch):
    from journal.services import backup_service
    from journal.ui import settings_cards

    class Broken:
        fallback_used = False

        def create_backup(self, kind):
            raise backup_service.BackupError("Не вдалося створити резервну копію.")

    warnings = []
    monkeypatch.setattr(backup_service.BackupService, "for_app", classmethod(lambda cls, d=None: Broken()))
    monkeypatch.setattr(settings_cards, "load_backup_dir", lambda: None)
    monkeypatch.setattr(backup_dialogs, "show_warning", lambda p, t, x: warnings.append(x))
    parent = QWidget()
    qtbot.addWidget(parent)
    backup_dialogs.default_exit_backup(parent)
    assert warnings and "Програма все одно закриється" in warnings[0]

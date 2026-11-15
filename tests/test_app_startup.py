"""Порядок запуску app.main(): відновлення після обриву — після ensure_running і до першого запиту."""
import sys

import pytest

from journal import app


class _Stop(Exception):
    pass


@pytest.fixture
def wired(monkeypatch):
    events = []

    class FakeApp:
        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def setApplicationVersion(self, version):
            pass

        def setWindowIcon(self, icon):
            pass

    class FakeAuth:
        def __init__(self, session):
            pass

        def has_any_teacher(self):
            events.append("query")
            return True

    class FakeScope:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    class StopDialog:
        def __init__(self):
            raise _Stop

    monkeypatch.setattr(sys, "argv", ["journal"])
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    monkeypatch.setattr(app, "install_excepthook", lambda: None)
    monkeypatch.setattr(app, "QApplication", FakeApp)
    monkeypatch.setattr(app, "app_icon", lambda: None)
    monkeypatch.setattr(app.single_instance, "acquire", lambda root=None: object())
    monkeypatch.setattr(app.single_instance, "create_app_mutex", lambda: None)
    monkeypatch.setattr(app, "apply_theme", lambda a, n: None)
    monkeypatch.setattr(app, "load_theme_name", lambda: "light")
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    monkeypatch.setattr(app.embedded_db, "ensure_running", lambda: events.append("ensure_running"))
    monkeypatch.setattr(app, "session_scope", lambda: FakeScope())
    monkeypatch.setattr(app, "AuthService", FakeAuth)
    monkeypatch.setattr(app, "LoginDialog", StopDialog)
    return events


def test_recovery_runs_between_ensure_running_and_first_query(monkeypatch, wired):
    monkeypatch.setattr(app, "recover_interrupted_restore", lambda: wired.append("recover") or False)
    with pytest.raises(_Stop):
        app.main()
    assert wired == ["ensure_running", "recover", "query"]


def test_restored_data_exits_with_code_zero_before_any_query(monkeypatch, wired):
    monkeypatch.setattr(app, "recover_interrupted_restore", lambda: wired.append("recover") or True)
    with pytest.raises(SystemExit) as caught:
        app.main()
    assert caught.value.code == 0
    assert wired == ["ensure_running", "recover"]

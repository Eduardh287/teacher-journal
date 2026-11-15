"""Одна запущена копія, версія, режим --smoke / --stop-server (етап 8b)."""
import socket
import sys
import tomllib

import pytest

from journal import app, single_instance
from journal.logging_setup import log_failure
from journal.version import FALLBACK_VERSION, app_version


def test_second_lock_is_refused_until_first_is_released(tmp_path):
    first = single_instance.acquire(tmp_path / "data")
    assert first is not None
    assert single_instance.acquire(tmp_path / "data") is None
    first.unlock()
    again = single_instance.acquire(tmp_path / "data")
    assert again is not None
    again.unlock()


def test_lock_in_non_ascii_folder(tmp_path):
    lock = single_instance.acquire(tmp_path / "дані журналу")
    assert lock is not None
    lock.unlock()


def test_stale_lock_of_dead_process_is_taken(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    # pid 0x7ffffff0 не існує: так виглядає замок після аварійного завершення
    (folder / single_instance.LOCK_FILE_NAME).write_text(f"2147483632\nTeacherJournal\n{socket.gethostname()}\n")
    lock = single_instance.acquire(folder)
    assert lock is not None
    lock.unlock()


def test_stale_lock_is_removed_and_retried(monkeypatch, tmp_path):
    calls = []

    class FakeLock:
        def __init__(self, path):
            self.attempts = 0

        def setStaleLockTime(self, ms): ...

        def tryLock(self, timeout):
            self.attempts += 1
            calls.append("try")
            return self.attempts == 2

        def removeStaleLockFile(self):
            calls.append("remove")
            return True

    monkeypatch.setattr(single_instance, "QLockFile", FakeLock)
    assert single_instance.acquire(tmp_path) is not None
    assert calls == ["try", "remove", "try"]


def test_lock_held_by_live_process_stays_refused(monkeypatch, tmp_path):
    class FakeLock:
        def __init__(self, path): ...
        def setStaleLockTime(self, ms): ...
        def tryLock(self, timeout):
            return False
        def removeStaleLockFile(self):
            return False

    monkeypatch.setattr(single_instance, "QLockFile", FakeLock)
    assert single_instance.acquire(tmp_path) is None


def test_create_app_mutex_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(single_instance.sys, "platform", "linux")
    monkeypatch.setattr(single_instance, "_mutex_handle", None)
    single_instance.create_app_mutex()
    assert single_instance._mutex_handle is None


def test_create_app_mutex_uses_the_installer_name(monkeypatch):
    import ctypes
    import types

    seen = {}

    def fake_create(attrs, owner, name):
        seen["name"] = name
        return 1234

    fake_create.argtypes = fake_create.restype = None
    kernel = types.SimpleNamespace(CreateMutexW=fake_create)
    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(single_instance, "_mutex_handle", None)
    single_instance.create_app_mutex()
    assert seen["name"] == "TeacherJournal-Running" and single_instance._mutex_handle == 1234


def test_stop_server_refuses_when_not_bundled(monkeypatch, capsys):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: False)
    monkeypatch.setattr(app.embedded_db, "stop_server_for_installer", lambda: pytest.fail("не мав запускатись"))
    assert app.run_stop_server() == 1
    assert "not bundled" in capsys.readouterr().out


def test_smoke_refuses_when_not_bundled(monkeypatch, capsys):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: False)
    monkeypatch.setattr(app.embedded_db, "ensure_running", lambda: pytest.fail("не мав запускатись"))
    assert app.run_smoke() == 1
    assert "SMOKE FAIL not bundled" in capsys.readouterr().out


def test_smoke_exits_with_already_open_code_and_touches_nothing(monkeypatch):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    monkeypatch.setattr(app.embedded_db, "ensure_running", lambda: pytest.fail("не мав запускатись"))
    monkeypatch.setattr(app.single_instance, "acquire", lambda root=None: None)
    assert app.run_smoke() == single_instance.ALREADY_OPEN_CODE


def test_stop_server_helper(monkeypatch):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    calls = []
    monkeypatch.setattr(app.embedded_db, "stop_server_for_installer", lambda: calls.append(1) or True)
    assert app.run_stop_server() == 0 and calls == [1]


def test_stop_server_helper_does_nothing_while_app_is_open(monkeypatch):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    monkeypatch.setattr(app.embedded_db, "stop_server_for_installer", lambda: pytest.fail("сервер потрібен програмі"))
    monkeypatch.setattr(app.single_instance, "acquire", lambda root=None: None)
    assert app.run_stop_server() == single_instance.ALREADY_OPEN_CODE


def test_stop_server_helper_never_raises(monkeypatch):
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(app.embedded_db, "stop_server_for_installer", boom)
    assert app.run_stop_server() == 1


def test_second_gui_launch_shows_message_and_exits(monkeypatch):
    shown = []

    class FakeApp:
        def __init__(self, argv): ...
        def setApplicationName(self, n): ...
        def setApplicationVersion(self, v): ...
        def setWindowIcon(self, i): ...

    monkeypatch.setattr(sys, "argv", ["journal"])
    monkeypatch.setattr(app, "setup_logging", lambda: None)
    monkeypatch.setattr(app, "install_excepthook", lambda: None)
    monkeypatch.setattr(app, "QApplication", FakeApp)
    monkeypatch.setattr(app, "app_icon", lambda: None)
    monkeypatch.setattr(app, "apply_theme", lambda a, n: None)
    monkeypatch.setattr(app, "load_theme_name", lambda: "light")
    monkeypatch.setattr(app.embedded_db, "is_bundled_mode", lambda: True)
    monkeypatch.setattr(app.embedded_db, "ensure_running", lambda: pytest.fail("друга копія не чіпає базу"))
    monkeypatch.setattr(app.single_instance, "acquire", lambda root=None: None)
    monkeypatch.setattr(app.single_instance, "create_app_mutex", lambda: None)
    monkeypatch.setattr(app.QMessageBox, "information", lambda parent, title, text: shown.append(text))
    with pytest.raises(SystemExit) as caught:
        app.main()
    assert caught.value.code == single_instance.ALREADY_OPEN_CODE
    assert shown == ["Програма вже відкрита."]


def test_fallback_version_matches_pyproject():
    from journal.config import PROJECT_ROOT

    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert FALLBACK_VERSION == data["project"]["version"]
    assert app_version()


def test_log_failure_keeps_type_but_not_message(caplog):
    with caplog.at_level("ERROR"):
        try:
            detail = "secret" + "-path teacher/file.xlsx"
            raise ValueError(detail)
        except ValueError:
            log_failure("Помилка")
    text = caplog.text
    assert "ValueError" in text and "Traceback" not in text
    assert "secret-path" not in text and "test_log_failure_keeps_type_but_not_message" in text

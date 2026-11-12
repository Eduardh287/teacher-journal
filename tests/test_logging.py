"""Тести налаштування логування. Не торкаються бази даних і не змінюють глобальний стан."""
import logging
import logging.handlers
import sys
import threading

import pytest

from journal import logging_setup


def _our_handlers():
    root = logging.getLogger()
    return [h for h in root.handlers if getattr(h, "_teacher_journal_handler", False)]


@pytest.fixture(autouse=True)
def _cleanup_logging():
    """Після кожного тесту прибирає наші обробники з кореневого логера."""
    root = logging.getLogger()
    level = root.level
    before = list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_setup_logging_writes_to_file(tmp_path):
    log_path = logging_setup.setup_logging(tmp_path)

    assert log_path == tmp_path / "journal.log"

    logging.getLogger("x").info("hello")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "hello" in log_path.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    logging_setup.setup_logging(tmp_path)
    logging_setup.setup_logging(tmp_path)

    ours = _our_handlers()
    file_handlers = [h for h in ours if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert len(ours) == 2  # файловий + stderr


def test_install_excepthook_logs_critical(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(logging_setup, "_original_excepthook", None)
    monkeypatch.setattr(sys, "excepthook", lambda *args: seen.append(args))
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)  # відновиться після тесту
    original = sys.excepthook

    log_path = logging_setup.setup_logging(tmp_path)
    logging_setup.install_excepthook()
    assert sys.excepthook is not original

    try:
        raise ValueError("boom")
    except ValueError as error:
        sys.excepthook(type(error), error, error.__traceback__)

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "CRITICAL" in content
    assert "boom" in content
    assert len(seen) == 1  # попередній обробник викликано


def test_detail_lines_with_row_data_are_redacted(tmp_path):
    """Рядок PostgreSQL «DETAIL: Failing row contains (...)» не потрапляє в журнал."""
    log_path = logging_setup.setup_logging(tmp_path)
    # Ім'я в змінній: traceback показує рядок коду з raise, і воно не має бути в ньому буквально.
    row = "(7, " + "Коваленко" + " Олена)"
    message = "new row violates check constraint\nDETAIL:  Failing row contains " + row
    try:
        raise ValueError(message)
    except ValueError:
        logging.getLogger("x").exception("Помилка БД")
    for handler in _our_handlers():
        handler.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "Коваленко" not in text
    assert logging_setup.REDACTED in text


def test_unwritable_log_dir_falls_back_to_stderr(tmp_path, monkeypatch):
    """Якщо файл журналу не відкривається, застосунок не падає — лише stderr."""
    def boom(*args, **kwargs):
        raise PermissionError("no access")

    monkeypatch.setattr(logging_setup, "RotatingFileHandler", boom)
    assert logging_setup.setup_logging(tmp_path) is None
    handlers = _our_handlers()
    assert len(handlers) == 1
    assert not isinstance(handlers[0], logging.handlers.RotatingFileHandler)

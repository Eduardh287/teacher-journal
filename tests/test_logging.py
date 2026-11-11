"""Тести налаштування логування. Не торкаються бази даних і не змінюють глобальний стан."""
import logging
import logging.handlers
import sys

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

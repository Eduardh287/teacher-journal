"""Налаштування логування: файл журналу з ротацією та вивід у stderr.

ПРАВИЛО: ніколи не логувати паролі, хеші паролів чи імена учнів.
У логах — лише ідентифікатори (id), наприклад student_id=42.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "journal.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

# Позначка на наших обробниках, щоб відрізняти їх від чужих і не дублювати при повторному виклику.
_HANDLER_TAG = "_teacher_journal_handler"

_original_excepthook = None


def log_dir() -> Path:
    """Повертає каталог логів і створює його, якщо його немає.

    Основний шлях: %LOCALAPPDATA%\\teacher-journal\\logs.
    Якщо LOCALAPPDATA не задано — ~/.teacher-journal/logs.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        path = Path(local_appdata) / "teacher-journal" / "logs"
    else:
        path = Path.home() / ".teacher-journal" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_our_handlers(root: logging.Logger) -> None:
    """Видаляє та закриває обробники, додані цим модулем."""
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()


def setup_logging(directory: Path | None = None) -> Path:
    """Налаштовує кореневий логер (рівень INFO) і повертає шлях до файлу журналу.

    Повторний виклик безпечний: попередні обробники цього модуля замінюються,
    дублікати не з'являються.
    """
    target_dir = Path(directory) if directory is not None else log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    _remove_our_handlers(root)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_TAG, True)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    setattr(stream_handler, _HANDLER_TAG, True)

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return log_path


def install_excepthook() -> None:
    """Підключає sys.excepthook, що записує необроблені винятки в журнал як CRITICAL.

    Після запису викликається попередній обробник, тож поведінка для користувача не змінюється.
    Повторний виклик не накопичує обгортки.
    """
    global _original_excepthook
    if _original_excepthook is None:
        _original_excepthook = sys.excepthook
    previous_hook = _original_excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, KeyboardInterrupt):
            logging.critical(
                "Необроблений виняток",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        previous_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook

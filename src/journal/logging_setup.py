"""Налаштування логування: файл журналу з ротацією та вивід у stderr.

ПРАВИЛО: ніколи не логувати паролі, хеші паролів чи імена учнів.
У логах — лише ідентифікатори (id), наприклад student_id=42.
"""
import logging
import os
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "journal.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

# Позначка на наших обробниках, щоб відрізняти їх від чужих і не дублювати при повторному виклику.
_HANDLER_TAG = "_teacher_journal_handler"

_original_excepthook = None

# PostgreSQL додає до помилок рядок «DETAIL: Failing row contains (...)» з даними рядка —
# там можуть бути імена учнів чи хеш пароля. Такі рядки в журнал не потрапляють.
_DETAIL_LINE = re.compile(r"^\s*DETAIL:.*$", re.MULTILINE)
REDACTED = "DETAIL: [приховано]"


class RedactingFormatter(logging.Formatter):
    """Форматувальник, що прибирає з тексту помилок дані рядків БД."""

    def format(self, record: logging.LogRecord) -> str:
        return _DETAIL_LINE.sub(REDACTED, super().format(record))


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


def setup_logging(directory: Path | None = None) -> Path | None:
    """Налаштовує кореневий логер (рівень INFO) і повертає шлях до файлу журналу.

    Повторний виклик безпечний: попередні обробники цього модуля замінюються,
    дублікати не з'являються.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    _remove_our_handlers(root)

    formatter = RedactingFormatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    setattr(stream_handler, _HANDLER_TAG, True)
    root.addHandler(stream_handler)

    # Якщо файл журналу недоступний (немає прав, файл заблоковано) — застосунок
    # однаково запускається, просто пише лише в stderr.
    try:
        target_dir = Path(directory) if directory is not None else log_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / LOG_FILE_NAME
        file_handler = RotatingFileHandler(
            log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        logging.getLogger(__name__).warning("Файл журналу недоступний — пишу лише в stderr")
        return None

    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_TAG, True)
    root.addHandler(file_handler)
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

    # Винятки у фонових потоках (з'являться, наприклад, для резервних копій) теж у журнал.
    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, KeyboardInterrupt):
            logging.critical(
                "Необроблений виняток у потоці %s",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

    threading.excepthook = _thread_hook

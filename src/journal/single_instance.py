"""Одна запущена копія застосунку: файл-замок у кореневій папці даних + іменований mutex для Inno Setup."""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile

from journal import embedded_db

LOCK_FILE_NAME = "app.lock"
MUTEX_NAME = "TeacherJournal-Running"  # той самий рядок — AppMutex в installer.iss
ALREADY_OPEN_CODE = 2
ALREADY_OPEN_TEXT = "Програма вже відкрита."

_mutex_handle = None  # тримаємо до кінця процесу


def acquire(root: Path | None = None) -> QLockFile | None:
    """Бере замок. None — його вже тримає інший запущений екземпляр.

    Замок прив'язаний до процесу: якщо програма завершилась аварійно, наступний запуск
    розпізнає застарілий замок (процесу вже немає) і забере його.
    """
    folder = root if root is not None else embedded_db.requested_root()
    folder.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(folder / LOCK_FILE_NAME))
    lock.setStaleLockTime(0)  # застарілим вважаємо лише замок мертвого процесу, не за часом
    if not lock.tryLock(0):
        return None
    return lock


def create_app_mutex() -> None:
    """Іменований mutex: за ним інсталятор бачить, що програма відкрита."""
    global _mutex_handle
    if sys.platform != "win32":
        return
    try:
        import ctypes

        create = ctypes.windll.kernel32.CreateMutexW
        create.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        create.restype = ctypes.c_void_p
        _mutex_handle = create(None, False, MUTEX_NAME)
    except Exception:  # noqa: BLE001 — без mutex програма працює, лише інсталятор не побачить її
        logging.warning("Не вдалося створити mutex програми", exc_info=True)

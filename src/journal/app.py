"""Точка входу: запуск застосунку."""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from journal import embedded_db, single_instance
from journal.config import ConfigError
from journal.db import session_scope
from journal.logging_setup import install_excepthook, setup_logging
from journal.version import app_version
from journal.services.auth_service import AuthService
from journal.ui.auth_dialogs import LoginDialog, RegisterDialog
from journal.ui.backup_dialogs import default_exit_backup, recover_interrupted_restore
from journal.ui.main_window import MainWindow
from journal.ui.rollover_dialog import maybe_run_rollover
from journal.ui.theme import apply_theme, load_theme_name


def app_icon() -> QIcon:
    """Іконка вікна: icon.ico поруч із ресурсами (збірка) або в packaging/ (розробка)."""
    root = embedded_db.resource_dir()
    for candidate in (root / "icon.ico", root / "packaging" / "icon.ico"):
        if candidate.is_file():
            return QIcon(str(candidate))
    return QIcon()


def run_smoke() -> int:
    """--smoke: підняти вбудовану БД, мігрувати, перевірити запит, зупинити. Без вікон.

    Лише у зібраній (bundled) версії: інакше можна зачепити робочу базу розробника.
    """
    if not embedded_db.is_bundled_mode():
        message = "SMOKE FAIL not bundled"
        if sys.stdout:
            print(message)
        return 1
    lock = single_instance.acquire()
    if lock is None:  # програма вже відкрита: ні бази, ні сервера не чіпаємо
        if sys.stdout:
            print("SMOKE SKIP already open")
        return single_instance.ALREADY_OPEN_CODE
    try:
        url = embedded_db.ensure_running()
        with session_scope() as session:
            AuthService(session).has_any_teacher()
        message = f"SMOKE OK {embedded_db.current_revision(url)}"
        code = 0
    except Exception as error:  # noqa: BLE001
        logging.exception("Smoke-тест не пройдено")
        message = f"SMOKE FAIL {type(error).__name__}"
        code = 1
    finally:
        embedded_db.stop()
        lock.unlock()
    # Віконний exe не має stdout — результат дублюється у файл.
    try:
        (embedded_db.requested_root() / "smoke_result.txt").write_text(message, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout:
        print(message)
    return code


def run_stop_server() -> int:
    """--stop-server: для інсталятора. Зупиняє сервер цієї установки; без вікон і без помилок назовні.

    Якщо програма відкрита (замок зайнятий) — нічого не чіпає: сервер потрібен їй.
    """
    lock = single_instance.acquire()
    if lock is None:
        return single_instance.ALREADY_OPEN_CODE
    try:
        stopped = embedded_db.stop_server_for_installer()
        logging.info("--stop-server: сервер зупинено=%s", stopped)
        return 0 if stopped else 1
    except Exception as error:  # noqa: BLE001 — інсталятор не мусить зупинятись через це
        logging.error("--stop-server не вдалося: %s", type(error).__name__)
        return 1
    finally:
        lock.unlock()


_instance_lock = None  # замок «одна копія» тримається до кінця процесу


def main() -> None:
    log_path = setup_logging()  # %LOCALAPPDATA%\teacher-journal\logs\journal.log
    install_excepthook()
    logging.info("Запуск застосунку; журнал: %s", log_path or "лише stderr")

    if "--stop-server" in sys.argv:
        sys.exit(run_stop_server())
    if "--smoke" in sys.argv:
        sys.exit(run_smoke())

    app = QApplication(sys.argv)
    app.setApplicationName("Електронний журнал")
    app.setApplicationVersion(app_version())
    app.setWindowIcon(app_icon())
    apply_theme(app, load_theme_name())

    global _instance_lock
    if embedded_db.is_bundled_mode():
        # Одна копія: друга не торкається ні бази, ні сервера першої.
        _instance_lock = single_instance.acquire()
        if _instance_lock is None:
            QMessageBox.information(None, "Електронний журнал", single_instance.ALREADY_OPEN_TEXT)
            sys.exit(single_instance.ALREADY_OPEN_CODE)
        single_instance.create_app_mutex()

    try:
        if embedded_db.is_bundled_mode():
            embedded_db.ensure_running()
        # До першого запиту: після обірваного відновлення таблиць може не бути зовсім.
        if recover_interrupted_restore():
            sys.exit(0)
        with session_scope() as session:
            first_run = not AuthService(session).has_any_teacher()
    except embedded_db.EmbeddedDbError as error:
        logging.exception("Вбудована база не запустилась")
        QMessageBox.critical(None, "Не вдалося запустити базу даних", str(error))
        sys.exit(1)
    except ConfigError as error:  # не налаштовано .env — показуємо конкретну причину
        logging.exception("Застосунок не налаштовано")
        QMessageBox.critical(None, "Помилка налаштування", str(error))
        sys.exit(1)
    except Exception:
        logging.exception("Не вдалося підключитися до бази даних")
        QMessageBox.critical(
            None,
            "Помилка",
            "Не вдалося підключитися до бази даних. Перевірте, що PostgreSQL запущено.",
        )
        sys.exit(1)

    dialog = RegisterDialog() if first_run else LoginDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    window = MainWindow(dialog.current_user, exit_backup=default_exit_backup)
    window.show()
    teacher_id = dialog.current_user.id
    QTimer.singleShot(0, lambda: maybe_run_rollover(window, teacher_id))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

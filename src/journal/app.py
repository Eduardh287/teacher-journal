"""Точка входу: запуск застосунку."""
import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from journal import embedded_db
from journal.config import ConfigError
from journal.db import session_scope
from journal.logging_setup import install_excepthook, setup_logging
from journal.services.auth_service import AuthService
from journal.ui.auth_dialogs import LoginDialog, RegisterDialog
from journal.ui.backup_dialogs import default_exit_backup
from journal.ui.main_window import MainWindow
from journal.ui.rollover_dialog import maybe_run_rollover
from journal.ui.theme import apply_theme, load_theme_name


def run_smoke() -> int:
    """--smoke: підняти вбудовану БД, мігрувати, перевірити запит, зупинити. Без вікон."""
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
    # Віконний exe не має stdout — результат дублюється у файл.
    try:
        (embedded_db.requested_root() / "smoke_result.txt").write_text(message, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout:
        print(message)
    return code


def main() -> None:
    log_path = setup_logging()  # %LOCALAPPDATA%\teacher-journal\logs\journal.log
    install_excepthook()
    logging.info("Запуск застосунку; журнал: %s", log_path or "лише stderr")

    if "--smoke" in sys.argv:
        sys.exit(run_smoke())

    app = QApplication(sys.argv)
    app.setApplicationName("Електронний журнал")
    apply_theme(app, load_theme_name())

    try:
        if embedded_db.is_bundled_mode():
            embedded_db.ensure_running()
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

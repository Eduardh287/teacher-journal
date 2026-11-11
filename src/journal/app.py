"""Точка входу: запуск застосунку."""
import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from journal.config import ConfigError
from journal.db import session_scope
from journal.logging_setup import install_excepthook, setup_logging
from journal.services.auth_service import AuthService
from journal.ui.auth_dialogs import LoginDialog, RegisterDialog
from journal.ui.main_window import MainWindow
from journal.ui.theme import apply_theme, load_theme_name


def main() -> None:
    log_path = setup_logging()  # %LOCALAPPDATA%\teacher-journal\logs\journal.log
    install_excepthook()
    logging.info("Запуск застосунку; журнал: %s", log_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Електронний журнал")
    apply_theme(app, load_theme_name())

    try:
        with session_scope() as session:
            first_run = not AuthService(session).has_any_teacher()
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

    window = MainWindow(dialog.current_user)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

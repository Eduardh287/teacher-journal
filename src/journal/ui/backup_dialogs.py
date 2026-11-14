"""Діалоги резервних копій: «зачекайте», підтвердження відновлення, копія при виході (етап 7a)."""
import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout, QWidget

from journal.services.backup_service import BackupInfo
from journal.ui.journal_dialogs import _TypedConfirmDialog
from journal.ui.widgets import label

RESTORE_WORD = "відновити"
FALLBACK_TEXT = "Обрана папка недоступна, тому копію збережено в типовій папці програми."


class BusyDialog(QDialog):
    """Маленьке вікно «зачекайте» без кнопок: показується на час довгої дії."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Зачекайте")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(label(text, wrap=True))


def run_busy(parent: QWidget | None, text: str, action: Callable[[], object]):
    """Виконує `action`, поки показано вікно «зачекайте». Винятки пробиваються далі."""
    dialog = BusyDialog(text, parent)
    dialog.show()
    QApplication.processEvents()
    try:
        return action()
    finally:
        dialog.close()
        dialog.deleteLater()


class RestoreConfirmDialog(_TypedConfirmDialog):
    """Підтвердження відновлення словом «відновити» (той самий шаблон, що й видалення журналу)."""

    def __init__(self, info: BackupInfo, parent: QWidget | None = None) -> None:
        self.info = info
        super().__init__(
            "Відновити з копії",
            "Відновити дані з копії?",
            f"Копія від {info.created:%d.%m.%Y %H:%M} ({info.kind_title}). "
            "Усі поточні дані буде замінено даними з копії. Перед цим програма збереже копію "
            "поточного стану. Після відновлення входьте з паролем, який діяв на момент створення копії, "
            "а програма закриється — відкрийте її знову.",
            parent,
            word=RESTORE_WORD,
            confirm_text="Відновити",
        )


def confirm_restore(parent: QWidget | None, info: BackupInfo) -> bool:
    return RestoreConfirmDialog(info, parent).exec() == QDialog.DialogCode.Accepted


def show_info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def show_warning(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def default_exit_backup(parent: QWidget | None) -> None:
    """Автоматична копія при закритті вікна. Помилка — попередження, застосунок усе одно закривається."""
    from journal.services.backup_service import BackupError, BackupService
    from journal.ui.settings_cards import load_backup_dir

    try:
        service = BackupService.for_app(load_backup_dir())
        run_busy(parent, "Створюю резервну копію…", lambda: service.create_backup("auto"))
        if service.fallback_used:
            show_info(parent, "Резервна копія", FALLBACK_TEXT)
    except BackupError as error:
        logging.warning("Автоматична копія при виході не створена: %s", error)
        show_warning(parent, "Резервна копія", f"{error}\nПрограма все одно закриється.")
    except Exception:
        logging.exception("Автоматична копія при виході не створена")
        show_warning(
            parent,
            "Резервна копія",
            "Не вдалося створити резервну копію. Деталі — у журналі.\nПрограма все одно закриється.",
        )

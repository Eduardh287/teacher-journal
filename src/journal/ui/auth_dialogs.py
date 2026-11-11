"""Діалоги першої реєстрації та входу викладача."""
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout, QWidget

from journal.db import session_scope
from journal.services.auth_service import AuthError, AuthService, CurrentUser
from journal.ui.widgets import brand_mark, button, field, label

DB_ERROR_TEXT = "Не вдалося підключитися до бази даних"


class _AuthDialog(QDialog):
    """Спільна основа: логотип і заголовок, рядок помилки, безпечний виклик AuthService."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self.current_user: CurrentUser | None = None

        self.error_label = QLabel()
        self.error_label.setProperty("error", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(40, 36, 40, 36)
        self.body.setSpacing(14)
        self.body.addWidget(brand_mark(48), alignment=Qt.AlignmentFlag.AlignHCenter)
        app_title = label("Електронний журнал", object_name="AppTitle")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(app_title)
        sub = label(subtitle, muted=True, wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(sub)
        self.body.addSpacing(10)

    @staticmethod
    def _edit(placeholder: str, password: bool = False) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def _finish_layout(self, fields: list[QWidget], submit_text: str, on_submit: Callable) -> None:
        for widget in fields:
            self.body.addWidget(widget)
        self.body.addWidget(self.error_label)
        self.body.addSpacing(6)
        self.submit_button = button(submit_text, variant="primary")
        self.submit_button.setDefault(True)  # Enter у будь-якому полі запускає дію
        self.submit_button.setMinimumHeight(40)
        self.submit_button.clicked.connect(on_submit)
        self.body.addWidget(self.submit_button)

    def show_error(self, text: str) -> None:
        """Показує помилку прямо в діалозі (без спливаючих вікон)."""
        self.error_label.setText(text)
        self.error_label.show()

    def run_db(self, action: Callable[[AuthService], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат).

        AuthError ловимо ПОЗА блоком with, щоб транзакція відкотилась.
        """
        try:
            with session_scope() as session:
                result = action(AuthService(session))
        except AuthError as error:
            self.show_error(str(error))
            return False, None
        except Exception:
            logging.exception("Помилка під час звернення до бази даних")
            self.show_error(DB_ERROR_TEXT)
            return False, None
        return True, result


class RegisterDialog(_AuthDialog):
    """Створення облікового запису при першому запуску."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Створення облікового запису",
            "Це перший запуск. Створіть обліковий запис викладача.",
            parent,
        )
        self.full_name_edit = self._edit("Напр. Олена Іванівна Коваль")
        self.username_edit = self._edit("Латинські літери та цифри")
        self.password_edit = self._edit("Щонайменше 8 символів", password=True)
        self.repeat_edit = self._edit("Ще раз той самий пароль", password=True)
        self._finish_layout(
            [
                field("ІМ'Я ТА ПО БАТЬКОВІ", self.full_name_edit),
                field("ЛОГІН", self.username_edit),
                field("ПАРОЛЬ", self.password_edit),
                field("ПОВТОРІТЬ ПАРОЛЬ", self.repeat_edit),
            ],
            "Створити обліковий запис",
            self._on_create,
        )

    def _on_create(self) -> None:
        password = self.password_edit.text()
        if password != self.repeat_edit.text():
            self.show_error("Паролі не збігаються")
            return

        ok, user = self.run_db(
            lambda auth: auth.register(
                self.username_edit.text(), password, self.full_name_edit.text()
            )
        )
        if ok:
            self.current_user = user
            self.accept()


class LoginDialog(_AuthDialog):
    """Вхід існуючого викладача."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Вхід", "Увійдіть, щоб продовжити роботу з журналом.", parent)
        self.username_edit = self._edit("Ваш логін")
        self.password_edit = self._edit("Ваш пароль", password=True)
        self._finish_layout(
            [field("ЛОГІН", self.username_edit), field("ПАРОЛЬ", self.password_edit)],
            "Увійти",
            self._on_login,
        )

    def _on_login(self) -> None:
        ok, user = self.run_db(
            lambda auth: auth.authenticate(self.username_edit.text(), self.password_edit.text())
        )
        if not ok:
            return
        if user is None:
            self.show_error("Невірний логін або пароль")
            self.password_edit.clear()
            self.password_edit.setFocus()
            return
        self.current_user = user
        self.accept()

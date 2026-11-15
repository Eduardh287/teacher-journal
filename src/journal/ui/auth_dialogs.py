"""Діалоги першої реєстрації та входу викладача."""
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLineEdit, QWidget

from journal.services.auth_service import AuthError, AuthService, CurrentUser
from journal.ui.service_scope import service_scope
from journal.ui.widgets import FormDialog, brand_mark, button, field, label

DB_ERROR_TEXT = "Не вдалося підключитися до бази даних"
LEGACY_CODE_LEAD_IN = "Тепер у програмі є код відновлення пароля."
RECOVERY_HINT = (
    "Запишіть код і зберігайте окремо від комп'ютера. "
    "Він знадобиться, якщо ви забудете пароль."
)


def run_auth_action(action: Callable[[AuthService], Any]) -> Any:
    """Виконує action в одній транзакції.

    Помилка, що має зберегти зміни (лічильник невдалих спроб), піднімається ПІСЛЯ commit;
    решта AuthError відкочують транзакцію.
    """
    kept: AuthError | None = None
    with service_scope(AuthService) as service:
        try:
            result = action(service)
        except AuthError as error:
            if not error.persist:
                raise
            kept = error
    if kept is not None:
        raise kept
    return result


class RecoveryCodeDialog(FormDialog):
    """Показує код відновлення один раз. Закрити можна лише кнопкою «Я записала код»."""

    def __init__(self, code: str, parent: QWidget | None = None, lead_in: str = "") -> None:
        super().__init__("Код відновлення", parent, heading="", width=460, fixed_width=True)
        self.code = code
        self._confirmed = False

        body = self.body
        if lead_in:
            body.addWidget(label(lead_in, wrap=True))
        body.addWidget(label("Ваш код відновлення", object_name="CardTitle"))
        self.code_label = label(code, object_name="RecoveryCode")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.code_label)
        body.addWidget(label(RECOVERY_HINT, muted=True, wrap=True))

        row = QHBoxLayout()
        self.copy_button = button("Скопіювати")
        self.copy_button.clicked.connect(self._on_copy)
        self.confirm_button = button("Я записала код", variant="primary")
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self._on_confirm)
        row.addWidget(self.copy_button)
        row.addStretch(1)
        row.addWidget(self.confirm_button)
        body.addLayout(row)
        self.copied_label = label("Скопійовано", muted=True)
        self.copied_label.hide()
        body.addWidget(self.copied_label)

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self.code)
        self.copied_label.show()

    def _on_confirm(self) -> None:
        self._confirmed = True
        self.accept()

    # Без підтвердження закрити не можна: Esc і хрестик ігноруються.
    def reject(self) -> None:
        if self._confirmed:
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._confirmed:
            event.accept()
        else:
            event.ignore()


def show_recovery_code(parent: QWidget | None, code: str, lead_in: str = "") -> None:
    RecoveryCodeDialog(code, parent, lead_in).exec()


class _AuthDialog(FormDialog):
    """Спільна основа: логотип і заголовок, рядок помилки, безпечний виклик AuthService."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent, heading="", width=420, fixed_width=True, margins=(40, 36))
        self.current_user: CurrentUser | None = None
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
        self.submit_button = self.add_submit(submit_text, on_submit)

    def run_db(self, action: Callable[[AuthService], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат)."""
        return self.run(
            lambda: run_auth_action(action), AuthError, "Помилка під час звернення до бази даних", DB_ERROR_TEXT
        )


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

        ok, result = self.run_db(
            lambda auth: auth.register(
                self.username_edit.text(), password, self.full_name_edit.text()
            )
        )
        if ok:
            user, code = result
            show_recovery_code(self, code)
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
        self.forgot_button = button("Забули пароль?", variant="ghost")
        self.forgot_button.clicked.connect(self._on_forgot)
        self.body.addWidget(self.forgot_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _on_forgot(self) -> None:
        dialog = ForgotPasswordDialog(self.username_edit.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.username_edit.setText(dialog.username_edit.text().strip())
            self.password_edit.clear()
            self.error_label.hide()
            self.password_edit.setFocus()

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
        self._offer_missing_recovery_code(user.id)
        self.accept()

    def _offer_missing_recovery_code(self, teacher_id: int) -> None:
        """Обліковий запис, створений до етапу 7b, отримує код при першому вході. Збій не заважає входу."""
        try:
            code = run_auth_action(lambda auth: auth.ensure_recovery_code(teacher_id))
            if code:
                show_recovery_code(self, code, lead_in=LEGACY_CODE_LEAD_IN)
        except Exception:
            logging.exception("Не вдалося видати код відновлення")


class ForgotPasswordDialog(_AuthDialog):
    """Новий пароль за кодом відновлення. Після успіху показує новий код."""

    def __init__(self, username: str = "", parent: QWidget | None = None) -> None:
        super().__init__(
            "Відновлення пароля",
            "Введіть логін, код відновлення та новий пароль.",
            parent,
        )
        self.username_edit = self._edit("Ваш логін")
        self.username_edit.setText(username)
        self.code_edit = self._edit("Напр. K7QM-3XPA-…")
        self.password_edit = self._edit("Щонайменше 8 символів", password=True)
        self.repeat_edit = self._edit("Ще раз той самий пароль", password=True)
        self._finish_layout(
            [
                field("ЛОГІН", self.username_edit),
                field("КОД ВІДНОВЛЕННЯ", self.code_edit),
                field("НОВИЙ ПАРОЛЬ", self.password_edit),
                field("ПОВТОРІТЬ ПАРОЛЬ", self.repeat_edit),
            ],
            "Змінити пароль",
            self._on_reset,
        )

    def _on_reset(self) -> None:
        password = self.password_edit.text()
        if password != self.repeat_edit.text():
            self.show_error("Паролі не збігаються")
            return
        ok, code = self.run_db(
            lambda auth: auth.reset_with_recovery_code(
                self.username_edit.text(), self.code_edit.text(), password
            )
        )
        if not ok:
            self.code_edit.clear()
            return
        show_recovery_code(self, code)
        self.accept()

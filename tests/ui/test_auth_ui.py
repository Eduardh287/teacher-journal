"""Діалоги реєстрації/входу/відновлення та картка «Обліковий запис» (offscreen, світла й темна теми)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QDialog

from journal.services.auth_service import AuthError, AuthService
from journal.ui import auth_dialogs, theme
from journal.ui import service_scope as service_scope_module
from journal.ui.auth_dialogs import (
    ForgotPasswordDialog,
    LoginDialog,
    RecoveryCodeDialog,
    RegisterDialog,
)
from journal.ui.settings_cards import AccountCard

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-long-password"


@pytest.fixture(params=["light", "dark"])
def themed(request, qapp):
    theme.apply_theme(qapp, request.param)
    return request.param


@pytest.fixture
def wired(session, monkeypatch):
    """Дії діалогів виконуються на сесії з відкатом; код відновлення не відкриває вікно, а запам'ятовується."""
    shown: list[str] = []

    def run(action):
        try:
            return action(AuthService(session))
        except AuthError:
            raise

    monkeypatch.setattr(auth_dialogs, "run_auth_action", run)
    monkeypatch.setattr(auth_dialogs, "show_recovery_code", lambda parent, code, lead_in="": shown.append((code, lead_in)))
    return shown


def make(qtbot, widget):
    qtbot.addWidget(widget)
    widget.show()
    return widget


def fill(dialog, **values):
    for name, text in values.items():
        getattr(dialog, f"{name}_edit").setText(text)


# ---------- діалог коду ----------

def test_recovery_dialog_shows_code_copy_and_confirm(qtbot, themed):
    dialog = make(qtbot, RecoveryCodeDialog("K7QM-3XPA-BBBB-CCCC"))
    assert dialog.code_label.text() == "K7QM-3XPA-BBBB-CCCC"
    assert dialog.code_label.objectName() == "RecoveryCode"
    assert dialog.copy_button.text() == "Скопіювати"
    assert dialog.confirm_button.text() == "Я записала код"
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == "K7QM-3XPA-BBBB-CCCC"
    assert dialog.copied_label.isVisible()
    assert dialog.grab().width() > 0  # відмальовується в обох темах


def test_recovery_dialog_cannot_be_dismissed_without_confirm(qtbot):
    dialog = make(qtbot, RecoveryCodeDialog("AAAA-BBBB-CCCC-DDDD"))
    dialog.reject()
    dialog.close()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.isVisible()
    dialog.closeEvent(event := QCloseEvent())
    assert not event.isAccepted()
    dialog.confirm_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not dialog.isVisible()


def test_recovery_dialog_text(qtbot):
    dialog = make(qtbot, RecoveryCodeDialog("AAAA-BBBB-CCCC-DDDD"))
    texts = [w.text() for w in dialog.findChildren(type(dialog.copied_label))]
    assert auth_dialogs.RECOVERY_HINT in texts
    assert "Запишіть код і зберігайте окремо від комп'ютера." in auth_dialogs.RECOVERY_HINT


# ---------- реєстрація ----------

def test_register_shows_code_once_then_accepts(qtbot, wired, themed):
    dialog = make(qtbot, RegisterDialog())
    fill(dialog, full_name="Олена Коваль", username="pytest_ui_reg", password=PASSWORD, repeat=PASSWORD)
    dialog.submit_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.current_user.username == "pytest_ui_reg"
    assert len(wired) == 1 and len(wired[0][0]) == 19


def test_register_error_shows_no_code(qtbot, wired):
    dialog = make(qtbot, RegisterDialog())
    fill(dialog, full_name="О", username="pytest_ui_reg2", password="short", repeat="short")
    dialog.submit_button.click()
    assert dialog.error_label.isVisible()
    assert wired == []


# ---------- вхід ----------

@pytest.fixture
def registered(session):
    AuthService(session).register("pytest_ui_login", PASSWORD, "Вхід")
    return session


def test_login_ok(qtbot, wired, registered, themed):
    dialog = make(qtbot, LoginDialog())
    fill(dialog, username="pytest_ui_login", password=PASSWORD)
    dialog.submit_button.click()
    assert dialog.current_user.username == "pytest_ui_login"


def test_login_lock_message_inline(qtbot, wired, registered, themed):
    dialog = make(qtbot, LoginDialog())
    fill(dialog, username="pytest_ui_login")
    for _ in range(5):
        dialog.password_edit.setText("wrong")
        dialog.submit_button.click()
    assert dialog.error_label.text() == "Невірний логін або пароль"
    dialog.password_edit.setText(PASSWORD)
    dialog.submit_button.click()
    assert dialog.error_label.isVisible()
    assert dialog.error_label.text().startswith("Забагато невдалих спроб. Спробуйте через ")
    assert dialog.current_user is None


def test_forgot_button_opens_dialog_and_returns_to_login(qtbot, wired, registered, monkeypatch):
    opened = []

    class FakeForgot:
        def __init__(self, username, parent):
            opened.append(username)
            self.username_edit = type("E", (), {"text": lambda self: " pytest_ui_login "})()

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(auth_dialogs, "ForgotPasswordDialog", FakeForgot)
    dialog = make(qtbot, LoginDialog())
    dialog.username_edit.setText("pytest_ui_login")
    dialog.password_edit.setText("old")
    assert dialog.forgot_button.text() == "Забули пароль?"
    dialog.forgot_button.click()
    assert opened == ["pytest_ui_login"]
    assert dialog.password_edit.text() == ""
    assert dialog.username_edit.text() == "pytest_ui_login"
    assert dialog.isVisible()  # лишаємось на вході


# ---------- забули пароль ----------

def test_forgot_dialog_resets_and_shows_new_code(qtbot, wired, session, themed):
    _, code = AuthService(session).register("pytest_ui_forgot", PASSWORD, "Забула")
    dialog = make(qtbot, ForgotPasswordDialog("pytest_ui_forgot"))
    fill(dialog, code=code.lower(), password=NEW_PASSWORD, repeat=NEW_PASSWORD)
    dialog.submit_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(wired) == 1 and wired[0][0] != code
    assert AuthService(session).authenticate("pytest_ui_forgot", NEW_PASSWORD) is not None


def test_forgot_dialog_wrong_code_and_mismatch(qtbot, wired, session):
    AuthService(session).register("pytest_ui_forgot2", PASSWORD, "Забула")
    dialog = make(qtbot, ForgotPasswordDialog("pytest_ui_forgot2"))
    fill(dialog, code="AAAA-AAAA-AAAA-AAAA", password=NEW_PASSWORD, repeat="zzz")
    dialog.submit_button.click()
    assert dialog.error_label.text() == "Паролі не збігаються"
    fill(dialog, repeat=NEW_PASSWORD)
    dialog.submit_button.click()
    assert dialog.error_label.text() == "Невірний логін або код відновлення"
    assert dialog.code_edit.text() == ""
    assert wired == []


# ---------- картка «Обліковий запис» ----------

@pytest.fixture
def card(qtbot, session):
    user, _ = AuthService(session).register("pytest_ui_card", PASSWORD, "Картка")
    shown = []
    widget = AccountCard(
        user.id,
        runner=lambda action: action(AuthService(session)),
        show_code=lambda parent, code: shown.append(code),
    )
    widget.shown = shown
    return make(qtbot, widget)


def fill_card(card, current="", new="", repeat=""):
    card.current_edit.setText(current)
    card.new_edit.setText(new)
    card.repeat_edit.setText(repeat)


def test_card_renders_in_both_themes(card, themed):
    assert card.change_button.text() == "Змінити пароль"
    assert card.current_edit.echoMode().name == "Password"
    assert card.grab().width() > 0


def test_card_changes_password_and_shows_code(card, session, themed):
    fill_card(card, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
    card.change_button.click()
    assert len(card.shown) == 1
    assert card.status.isVisible() and not card.error.isVisible()
    assert card.new_edit.text() == "" and card.current_edit.text() == ""
    assert AuthService(session).authenticate("pytest_ui_card", NEW_PASSWORD) is not None


@pytest.mark.parametrize(
    ("current", "new", "repeat", "message"),
    [
        (PASSWORD, NEW_PASSWORD, "different-password", "Нові паролі не збігаються"),
        (PASSWORD, "short", "short", "Пароль має містити щонайменше 8 символів"),
        ("wrong-current-pw", NEW_PASSWORD, NEW_PASSWORD, "Поточний пароль невірний"),
    ],
)
def test_card_inline_errors(card, current, new, repeat, message):
    fill_card(card, current, new, repeat)
    card.change_button.click()
    assert card.error.isVisible()
    assert card.error.text() == message
    assert card.shown == []


def test_card_shows_lock_message(card):
    for _ in range(5):
        fill_card(card, "wrong-current-pw", NEW_PASSWORD, NEW_PASSWORD)
        card.change_button.click()
    fill_card(card, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
    card.change_button.click()
    assert card.error.text().startswith("Забагато невдалих спроб. Спробуйте через ")
    assert card.shown == []


def test_run_auth_action_keeps_failure_counter(monkeypatch):
    """persist-помилка піднімається ПІСЛЯ commit; звичайна — відкочує транзакцію."""
    from contextlib import contextmanager

    from journal.services.auth_service import AuthFailed

    events = []

    @contextmanager
    def fake_scope():
        try:
            yield object()
        except BaseException:
            events.append("rollback")
            raise
        events.append("commit")

    monkeypatch.setattr(service_scope_module, "session_scope", fake_scope)
    monkeypatch.setattr(auth_dialogs, "AuthService", lambda s: s)

    def failed(_):
        raise AuthFailed("x")

    def plain(_):
        raise AuthError("x")

    with pytest.raises(AuthFailed):
        auth_dialogs.run_auth_action(failed)
    with pytest.raises(AuthError):
        auth_dialogs.run_auth_action(plain)
    assert events == ["commit", "rollback"]


def test_login_issues_code_for_pre_7b_account(qtbot, wired, registered, session):
    from journal.models import Teacher

    row = session.query(Teacher).filter_by(username="pytest_ui_login").one()
    row.recovery_code_hash = None
    dialog = make(qtbot, LoginDialog())
    fill(dialog, username="pytest_ui_login", password=PASSWORD)
    dialog.submit_button.click()
    assert dialog.current_user is not None
    assert len(wired) == 1
    assert wired[0][1] == "Тепер у програмі є код відновлення пароля."
    assert row.recovery_code_hash


def test_login_does_not_show_code_when_already_has_one(qtbot, wired, registered):
    dialog = make(qtbot, LoginDialog())
    fill(dialog, username="pytest_ui_login", password=PASSWORD)
    dialog.submit_button.click()
    assert dialog.current_user is not None
    assert wired == []


def test_login_survives_code_failure(qtbot, wired, registered, monkeypatch):
    dialog = make(qtbot, LoginDialog())
    fill(dialog, username="pytest_ui_login", password=PASSWORD)
    ok_run = auth_dialogs.run_auth_action
    calls = []

    def run(action):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("x")
        return ok_run(action)

    monkeypatch.setattr(auth_dialogs, "run_auth_action", run)
    dialog.submit_button.click()
    assert dialog.current_user is not None

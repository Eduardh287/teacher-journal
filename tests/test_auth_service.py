"""Тести AuthService: реєстрація, вхід, перевірка наявності викладачів.

Кожен тест працює в транзакції фікстури `session`, яка відкочується,
тож дані в БД не лишаються. Усі логіни мають префікс `pytest_`.
"""
import pytest

from journal.models import Teacher
from journal.services.auth_service import AuthError, AuthService, CurrentUser

PASSWORD = "correct-horse-battery"


@pytest.fixture
def auth(session) -> AuthService:
    return AuthService(session)


def test_register_returns_current_user(auth):
    user = auth.register("pytest_reg1", PASSWORD, "Іван Петренко")

    assert isinstance(user, CurrentUser)
    assert isinstance(user.id, int)
    assert user.username == "pytest_reg1"
    assert user.full_name == "Іван Петренко"


def test_register_stores_argon2_hash_not_plain_password(auth, session):
    user = auth.register("pytest_hash1", PASSWORD, "Олена Коваль")

    teacher = session.get(Teacher, user.id)
    assert teacher is not None
    assert teacher.password_hash != PASSWORD
    assert teacher.password_hash.startswith("$argon2")


def test_register_strips_spaces_from_username_and_full_name(auth, session):
    user = auth.register("  pytest_strip  ", PASSWORD, "  Марія Савчук  ")

    assert user.username == "pytest_strip"
    assert user.full_name == "Марія Савчук"

    teacher = session.get(Teacher, user.id)
    assert teacher.username == "pytest_strip"
    assert teacher.full_name == "Марія Савчук"


@pytest.mark.parametrize(
    "username",
    ["ab", "вчитель", "my name"],
    ids=["too_short", "cyrillic", "with_space"],
)
def test_register_rejects_invalid_username(auth, username):
    with pytest.raises(AuthError):
        auth.register(username, PASSWORD, "Тест Викладач")


def test_register_rejects_short_password(auth):
    with pytest.raises(AuthError):
        auth.register("pytest_shortpw", "short7!", "Тест Викладач")  # 7 символів


@pytest.mark.parametrize("full_name", ["", "   "], ids=["empty", "whitespace"])
def test_register_rejects_empty_full_name(auth, full_name):
    with pytest.raises(AuthError):
        auth.register("pytest_noname", PASSWORD, full_name)


def test_register_rejects_duplicate_username(auth):
    auth.register("pytest_dup", PASSWORD, "Перший")

    with pytest.raises(AuthError):
        auth.register("pytest_dup", PASSWORD, "Другий")


def test_register_rejects_duplicate_username_differing_only_by_case(auth):
    auth.register("pytest_Teacher1", PASSWORD, "Перший")

    with pytest.raises(AuthError):
        auth.register("pytest_teacher1", PASSWORD, "Другий")


def test_authenticate_correct_password_returns_same_user(auth):
    registered = auth.register("pytest_login1", PASSWORD, "Вхід Перший")

    user = auth.authenticate("pytest_login1", PASSWORD)

    assert isinstance(user, CurrentUser)
    assert user.id == registered.id


def test_authenticate_is_case_insensitive_for_username(auth):
    registered = auth.register("pytest_LoginCase", PASSWORD, "Вхід Другий")

    user = auth.authenticate("PYTEST_logincase", PASSWORD)

    assert user is not None
    assert user.id == registered.id


def test_authenticate_wrong_password_returns_none(auth):
    auth.register("pytest_wrongpw", PASSWORD, "Невірний Пароль")

    assert auth.authenticate("pytest_wrongpw", "wrong-password-value") is None


def test_authenticate_unknown_username_returns_none(auth):
    assert auth.authenticate("pytest_nobody_here", PASSWORD) is None


def test_has_any_teacher_true_after_register(auth):
    # Не перевіряємо початковий стан: у dev-БД можуть уже бути викладачі.
    auth.register("pytest_hasany", PASSWORD, "Є Викладач")

    assert auth.has_any_teacher() is True

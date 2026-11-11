"""Реєстрація та вхід викладача.

Паролі зберігаються лише як хеш Argon2 (рекомендований алгоритм OWASP).
Сервіс отримує Session ззовні: транзакцією керує той, хто викликає (UI або тест).
"""
import re
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from journal.models import Teacher
from journal.repositories.teacher_repository import TeacherRepository

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
MIN_PASSWORD_LENGTH = 8

_hasher = PasswordHasher()
# Хеш-заглушка: перевіряємо пароль навіть для неіснуючого логіну,
# щоб час відповіді не підказував, чи існує такий користувач.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class AuthError(Exception):
    """Помилка з повідомленням, яке можна показати користувачу."""


@dataclass(frozen=True)
class CurrentUser:
    """Дані про того, хто увійшов. Не ORM-об'єкт, щоб UI не залежав від сесії БД."""

    id: int
    username: str
    full_name: str


class AuthService:
    def __init__(self, session: Session) -> None:
        self.teachers = TeacherRepository(session)

    def has_any_teacher(self) -> bool:
        return self.teachers.count() > 0

    def register(self, username: str, password: str, full_name: str) -> CurrentUser:
        username = username.strip()
        full_name = full_name.strip()
        if not USERNAME_RE.match(username):
            raise AuthError("Логін: 3–50 символів, латинські літери, цифри, _ . -")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"Пароль має містити щонайменше {MIN_PASSWORD_LENGTH} символів")
        if not full_name:
            raise AuthError("Вкажіть ім'я")
        if self.teachers.get_by_username(username) is not None:
            raise AuthError("Такий логін уже зайнятий")

        teacher = self.teachers.add(
            Teacher(username=username, password_hash=_hasher.hash(password), full_name=full_name)
        )
        return _to_current_user(teacher)

    def authenticate(self, username: str, password: str) -> CurrentUser | None:
        """Повертає користувача або None. Причину (логін чи пароль) навмисно не розкриваємо."""
        teacher = self.teachers.get_by_username(username.strip())
        stored_hash = teacher.password_hash if teacher else _DUMMY_HASH
        try:
            _hasher.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return None
        if teacher is None:
            return None
        if _hasher.check_needs_rehash(teacher.password_hash):
            teacher.password_hash = _hasher.hash(password)
        return _to_current_user(teacher)


def _to_current_user(teacher: Teacher) -> CurrentUser:
    return CurrentUser(id=teacher.id, username=teacher.username, full_name=teacher.full_name)

"""Реєстрація, вхід, зміна пароля та відновлення доступу викладача.

Паролі й коди відновлення зберігаються лише як хеш Argon2 (рекомендований алгоритм OWASP).
Сервіс отримує Session ззовні: транзакцією керує той, хто викликає (UI або тест).

Захист від підбору: після MAX_FREE_FAILURES невдач підряд вхід блокується на LOCK_BASE_SECONDS,
далі тривалість подвоюється з кожною невдачею, максимум LOCK_MAX_SECONDS. Для існуючого логіну
лічильник лежить у БД (teachers), для неіснуючого — у пам'яті процесу, тож відповідь однакова.
Поки вхід заблоковано, пароль не перевіряється взагалі.
Паролі, коди й хеші ніколи не потрапляють у журнал.
"""
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from journal.models import Teacher
from journal.repositories.teacher_repository import TeacherRepository

log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
MIN_PASSWORD_LENGTH = 8

MAX_FREE_FAILURES = 5
LOCK_BASE_SECONDS = 30
LOCK_MAX_SECONDS = 15 * 60

# Без схожих символів (I, L, O, 0, 1): код переписують з паперу.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_GROUPS = 4
RECOVERY_GROUP_LENGTH = 4

_hasher = PasswordHasher()
# Хеш-заглушка: перевіряємо пароль навіть для неіснуючого логіну,
# щоб час відповіді не підказував, чи існує такий користувач.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


# Лічильники для неіснуючих логінів: ключ — логін у нижньому регістрі. Лише пам'ять процесу.
_unknown_state: dict[str, "_Throttle"] = {}
_UNKNOWN_STATE_LIMIT = 1000
BAD_CREDENTIALS = "Невірний логін або пароль"
BAD_RECOVERY = "Невірний логін або код відновлення"


class AuthError(Exception):
    """Помилка з повідомленням, яке можна показати користувачу.

    persist=True — зміни в БД (лічильник невдач) треба зберегти попри помилку.
    """

    persist = False


class AuthFailed(AuthError):
    """Невірні дані; лічильник невдач збільшено, його треба зберегти."""

    persist = True


class AuthLocked(AuthError):
    """Вхід тимчасово заблоковано; seconds — скільки лишилось."""

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(locked_message(seconds))


def locked_message(seconds: int) -> str:
    seconds = max(1, int(seconds))
    if seconds >= 60:
        left = f"{-(-seconds // 60)} хв."
    else:
        left = f"{seconds} с."
    return f"Забагато невдалих спроб. Спробуйте через {left}"


def lock_seconds_for(failures: int) -> int:
    """Тривалість блокування після failures-ї невдачі підряд (0 — ще без блокування)."""
    if failures < MAX_FREE_FAILURES:
        return 0
    return min(LOCK_BASE_SECONDS * 2 ** (failures - MAX_FREE_FAILURES), LOCK_MAX_SECONDS)


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()


def generate_recovery_code() -> str:
    groups = [
        "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_GROUP_LENGTH))
        for _ in range(RECOVERY_GROUPS)
    ]
    return "-".join(groups)


@dataclass
class _Throttle:
    """Стан захисту від підбору для одного логіну (у БД або в пам'яті)."""

    failed_attempts: int = 0
    locked_until: datetime | None = None


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@dataclass(frozen=True)
class CurrentUser:
    """Дані про того, хто увійшов. Не ORM-об'єкт, щоб UI не залежав від сесії БД."""

    id: int
    username: str
    full_name: str


class AuthService:
    def __init__(self, session: Session, clock: Clock = _utc_now) -> None:
        self.teachers = TeacherRepository(session)
        self._clock = clock

    def has_any_teacher(self) -> bool:
        return self.teachers.count() > 0

    # ---------- захист від підбору ----------

    def _state(self, username: str, teacher: Teacher | None) -> _Throttle | Teacher:
        """Об'єкт зі полями failed_attempts/locked_until: викладач із БД або запис у пам'яті."""
        if teacher is not None:
            return teacher
        if len(_unknown_state) > _UNKNOWN_STATE_LIMIT:
            now = self._clock()
            for key in [k for k, v in _unknown_state.items() if not v.locked_until or v.locked_until <= now]:
                del _unknown_state[key]
        return _unknown_state.setdefault(username.strip().lower(), _Throttle())

    def _check_not_locked(self, state: _Throttle | Teacher) -> None:
        until = _aware(state.locked_until)
        if until is None:
            return
        remaining = (until - self._clock()).total_seconds()
        if remaining > 0:
            raise AuthLocked(int(-(-remaining // 1)))

    def _register_failure(self, state: _Throttle | Teacher, username: str) -> None:
        state.failed_attempts = (state.failed_attempts or 0) + 1
        delay = lock_seconds_for(state.failed_attempts)
        state.locked_until = self._clock() + timedelta(seconds=delay) if delay else None
        log.warning("failed login for %s (attempt %d)", username.strip(), state.failed_attempts)

    @staticmethod
    def _reset_state(state: _Throttle | Teacher) -> None:
        state.failed_attempts = 0
        state.locked_until = None

    # ---------- реєстрація та вхід ----------

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"Пароль має містити щонайменше {MIN_PASSWORD_LENGTH} символів")

    def register(self, username: str, password: str, full_name: str) -> tuple[CurrentUser, str]:
        """Створює викладача. Повертає (користувач, код відновлення — показати один раз)."""
        username = username.strip()
        full_name = full_name.strip()
        if not USERNAME_RE.match(username):
            raise AuthError("Логін: 3–50 символів, латинські літери, цифри, _ . -")
        self._validate_password(password)
        if not full_name:
            raise AuthError("Вкажіть ім'я")
        if self.teachers.get_by_username(username) is not None:
            raise AuthError("Такий логін уже зайнятий")

        code = generate_recovery_code()
        teacher = self.teachers.add(
            Teacher(
                username=username,
                password_hash=_hasher.hash(password),
                full_name=full_name,
                recovery_code_hash=_hasher.hash(normalize_recovery_code(code)),
            )
        )
        return _to_current_user(teacher), code

    def authenticate(self, username: str, password: str) -> CurrentUser | None:
        """Повертає користувача або None. Причину (логін чи пароль) навмисно не розкриваємо.

        Якщо вхід заблоковано — AuthLocked (пароль при цьому не перевіряється).
        """
        teacher = self.teachers.get_by_username(username.strip())
        state = self._state(username, teacher)
        self._check_not_locked(state)
        if not self._password_matches(teacher, password):
            self._register_failure(state, username)
            return None
        self._reset_state(state)
        if _hasher.check_needs_rehash(teacher.password_hash):
            teacher.password_hash = _hasher.hash(password)
        return _to_current_user(teacher)

    @staticmethod
    def _password_matches(teacher: Teacher | None, password: str) -> bool:
        stored_hash = teacher.password_hash if teacher else _DUMMY_HASH
        try:
            _hasher.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        return teacher is not None

    # ---------- зміна пароля та відновлення ----------

    def change_password(self, teacher_id: int, current: str, new: str) -> str:
        """Змінює пароль; повертає НОВИЙ код відновлення. Невірний поточний пароль — спроба."""
        teacher = self.teachers.get(teacher_id)
        if teacher is None:
            raise AuthError("Обліковий запис не знайдено")
        self._check_not_locked(teacher)
        self._validate_password(new)
        if not self._password_matches(teacher, current):
            self._register_failure(teacher, teacher.username)
            raise AuthFailed("Поточний пароль невірний")
        self._reset_state(teacher)
        return self._set_password(teacher, new)

    def reset_with_recovery_code(self, username: str, code: str, new_password: str) -> str:
        """Скидає пароль за кодом відновлення; повертає новий код. Обмеження — як при вході."""
        teacher = self.teachers.get_by_username(username.strip())
        state = self._state(username, teacher)
        self._check_not_locked(state)
        self._validate_password(new_password)
        stored = teacher.recovery_code_hash if teacher and teacher.recovery_code_hash else _DUMMY_HASH
        try:
            _hasher.verify(stored, normalize_recovery_code(code))
            matched = teacher is not None and teacher.recovery_code_hash is not None
        except (VerificationError, InvalidHashError):
            matched = False
        if not matched:
            self._register_failure(state, username)
            raise AuthFailed(BAD_RECOVERY)
        self._reset_state(teacher)
        return self._set_password(teacher, new_password)

    def ensure_recovery_code(self, teacher_id: int) -> str | None:
        """Для облікового запису без коду (створеного до етапу 7b) видає код; інакше None."""
        teacher = self.teachers.get(teacher_id)
        if teacher is None or teacher.recovery_code_hash:
            return None
        code = generate_recovery_code()
        teacher.recovery_code_hash = _hasher.hash(normalize_recovery_code(code))
        return code

    def admin_reset_password(self, username: str, new_password: str) -> str:
        """Скидання автором (scripts/reset_password.py): без старого пароля, знімає блокування."""
        teacher = self.teachers.get_by_username(username.strip())
        if teacher is None:
            raise AuthError("Користувача з таким логіном не знайдено")
        self._validate_password(new_password)
        self._reset_state(teacher)
        return self._set_password(teacher, new_password)

    def _set_password(self, teacher: Teacher, password: str) -> str:
        code = generate_recovery_code()
        teacher.password_hash = _hasher.hash(password)
        teacher.recovery_code_hash = _hasher.hash(normalize_recovery_code(code))
        return code


def _to_current_user(teacher: Teacher) -> CurrentUser:
    return CurrentUser(id=teacher.id, username=teacher.username, full_name=teacher.full_name)

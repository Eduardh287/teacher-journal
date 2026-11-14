"""Етап 7b: захист від підбору, зміна пароля, код відновлення. Лише journal_test (відкат)."""
import re
from datetime import UTC, datetime, timedelta

import pytest

from journal.models import Teacher
from journal.services import auth_service
from journal.services.auth_service import (
    RECOVERY_ALPHABET,
    AuthError,
    AuthLocked,
    AuthService,
    generate_recovery_code,
    locked_message,
    lock_seconds_for,
    normalize_recovery_code,
)

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-long-password"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def auth(session, clock) -> AuthService:
    return AuthService(session, clock=clock)


@pytest.fixture
def teacher(auth):
    user, code = auth.register("pytest_sec", PASSWORD, "Захист Тест")
    return user, code


def fail(auth, username="pytest_sec", times=1):
    for _ in range(times):
        assert auth.authenticate(username, "wrong-password") is None


def lock_remaining(auth, username="pytest_sec") -> int:
    with pytest.raises(AuthLocked) as info:
        auth.authenticate(username, PASSWORD)
    return info.value.seconds


# ---------- пороги й тривалість ----------

@pytest.mark.parametrize(
    ("failures", "seconds"),
    [(1, 0), (4, 0), (5, 30), (6, 60), (7, 120), (8, 240), (9, 480), (10, 900), (11, 900), (50, 900)],
)
def test_lock_seconds_schedule(failures, seconds):
    assert lock_seconds_for(failures) == seconds


def test_no_lock_before_fifth_failure(auth, teacher):
    fail(auth, times=4)
    assert auth.authenticate("pytest_sec", PASSWORD) is not None


def test_fifth_failure_locks_for_30_seconds(auth, teacher):
    fail(auth, times=5)
    assert lock_remaining(auth) == 30


def test_lock_expires_then_doubles_on_next_failure(auth, teacher, clock):
    fail(auth, times=5)
    clock.advance(31)
    fail(auth)  # 6-а невдача
    assert lock_remaining(auth) == 60


def test_lock_capped_at_15_minutes(auth, teacher, clock):
    for _ in range(12):
        fail(auth)
        clock.advance(1000)
    fail(auth)
    assert lock_remaining(auth) == 900


def test_success_resets_counter(auth, teacher, clock):
    fail(auth, times=4)
    assert auth.authenticate("pytest_sec", PASSWORD) is not None
    fail(auth, times=4)
    assert auth.authenticate("pytest_sec", PASSWORD) is not None  # ще не 5 підряд


def test_success_after_lock_expired_resets(auth, teacher, clock):
    fail(auth, times=5)
    clock.advance(31)
    assert auth.authenticate("pytest_sec", PASSWORD) is not None
    fail(auth, times=4)
    assert auth.authenticate("pytest_sec", PASSWORD) is not None


def test_correct_password_not_verified_while_locked(auth, teacher, monkeypatch):
    fail(auth, times=5)

    class NoVerify:
        def verify(self, *args, **kwargs):
            raise AssertionError("пароль не мав перевірятись")

    monkeypatch.setattr(auth_service, "_hasher", NoVerify())
    with pytest.raises(AuthLocked):
        auth.authenticate("pytest_sec", PASSWORD)


def test_lock_stored_in_db_in_utc(auth, teacher, session, clock):
    fail(auth, times=5)
    row = session.get(Teacher, teacher[0].id)
    assert row.failed_attempts == 5
    assert row.locked_until == clock.now + timedelta(seconds=30)
    assert row.locked_until.utcoffset() == timedelta(0)


def test_lock_survives_new_service_instance(session, teacher, clock):
    fail(AuthService(session, clock=clock), times=5)
    with pytest.raises(AuthLocked):
        AuthService(session, clock=clock).authenticate("pytest_sec", PASSWORD)


def test_lock_is_case_insensitive(auth, teacher):
    fail(auth, times=5)
    with pytest.raises(AuthLocked):
        auth.authenticate("PYTEST_SEC", PASSWORD)


# ---------- неіснуючі логіни ----------

def test_unknown_user_throttled_identically(auth, teacher, clock):
    fail(auth, "pytest_ghost", times=4)
    assert auth.authenticate("pytest_ghost", "x") is None
    # 5-а невдача для неіснуючого — той самий блок на 30 с, що й для справжнього
    assert lock_remaining(auth, "pytest_ghost") == 30
    clock.advance(31)
    fail(auth, "pytest_ghost")
    assert lock_remaining(auth, "pytest_ghost") == 60


def test_unknown_and_known_give_same_messages(session, clock):
    real = AuthService(session, clock=clock)
    real.register("pytest_real", PASSWORD, "Справжній")
    fail(real, "pytest_real", times=5)
    fail(real, "pytest_nobody", times=5)
    texts = []
    for name in ("pytest_real", "pytest_nobody"):
        with pytest.raises(AuthLocked) as info:
            real.authenticate(name, "x")
        texts.append(str(info.value))
    assert texts[0] == texts[1]


def test_unknown_state_keyed_lowercase(auth):
    fail(auth, "Pytest_Ghost", times=5)
    with pytest.raises(AuthLocked):
        auth.authenticate("pytest_ghost", "x")


def test_unknown_state_is_pruned(auth, monkeypatch):
    monkeypatch.setattr(auth_service, "_UNKNOWN_STATE_LIMIT", 3)
    for i in range(10):
        fail(auth, f"pytest_g{i}")
    assert len(auth_service._unknown_state) <= 4


# ---------- повідомлення ----------

@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (1, "Забагато невдалих спроб. Спробуйте через 1 с."),
        (30, "Забагато невдалих спроб. Спробуйте через 30 с."),
        (59, "Забагато невдалих спроб. Спробуйте через 59 с."),
        (60, "Забагато невдалих спроб. Спробуйте через 1 хв."),
        (61, "Забагато невдалих спроб. Спробуйте через 2 хв."),
        (900, "Забагато невдалих спроб. Спробуйте через 15 хв."),
    ],
)
def test_locked_message(seconds, text):
    assert locked_message(seconds) == text


def test_locked_exception_carries_seconds(auth, teacher):
    fail(auth, times=5)
    with pytest.raises(AuthLocked) as info:
        auth.authenticate("pytest_sec", PASSWORD)
    assert info.value.seconds == 30
    assert "30 с." in str(info.value)


# ---------- код відновлення ----------

def test_recovery_code_format():
    pattern = rf"^[{RECOVERY_ALPHABET}]{{4}}(-[{RECOVERY_ALPHABET}]{{4}}){{3}}$"
    codes = {generate_recovery_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(re.match(pattern, c) for c in codes)
    assert not set("ILO01") & set(RECOVERY_ALPHABET)


@pytest.mark.parametrize("raw", ["k7qm-3xpa-bbbb-cccc", " K7QM 3XPA BBBB CCCC ", "K7QM3XPABBBBCCCC"])
def test_recovery_code_normalisation(raw):
    assert normalize_recovery_code(raw) == "K7QM3XPABBBBCCCC"


def test_registration_issues_code_stored_hashed(auth, session, teacher):
    user, code = teacher
    row = session.get(Teacher, user.id)
    assert row.recovery_code_hash.startswith("$argon2")
    assert code not in row.recovery_code_hash
    assert normalize_recovery_code(code) not in row.recovery_code_hash


def test_authenticate_does_not_issue_code(auth, teacher, session):
    before = session.get(Teacher, teacher[0].id).recovery_code_hash
    auth.authenticate("pytest_sec", PASSWORD)
    assert session.get(Teacher, teacher[0].id).recovery_code_hash == before


# ---------- change_password ----------

def test_change_password_returns_new_code_and_works(auth, teacher):
    user, old_code = teacher
    new_code = auth.change_password(user.id, PASSWORD, NEW_PASSWORD)
    assert new_code != old_code
    assert auth.authenticate("pytest_sec", NEW_PASSWORD) is not None
    assert auth.authenticate("pytest_sec", PASSWORD) is None


def test_change_password_invalidates_old_code(auth, teacher):
    user, old_code = teacher
    new_code = auth.change_password(user.id, PASSWORD, NEW_PASSWORD)
    with pytest.raises(AuthError):
        auth.reset_with_recovery_code("pytest_sec", old_code, "yet-another-pass")
    auth.reset_with_recovery_code("pytest_sec", new_code, "yet-another-pass")


def test_change_password_wrong_current_counts_attempt(auth, teacher, session):
    with pytest.raises(AuthError) as info:
        auth.change_password(teacher[0].id, "nope-nope-nope", NEW_PASSWORD)
    assert info.value.persist is True
    assert session.get(Teacher, teacher[0].id).failed_attempts == 1
    assert auth.authenticate("pytest_sec", PASSWORD) is not None


def test_change_password_wrong_current_five_times_locks(auth, teacher):
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.change_password(teacher[0].id, "nope-nope-nope", NEW_PASSWORD)
    with pytest.raises(AuthLocked):
        auth.change_password(teacher[0].id, PASSWORD, NEW_PASSWORD)


def test_change_password_rejects_short_new_password(auth, teacher, session):
    with pytest.raises(AuthError, match="щонайменше 8"):
        auth.change_password(teacher[0].id, PASSWORD, "short")
    assert session.get(Teacher, teacher[0].id).failed_attempts == 0


def test_change_password_unknown_teacher(auth):
    with pytest.raises(AuthError):
        auth.change_password(999_999_999, PASSWORD, NEW_PASSWORD)


# ---------- reset_with_recovery_code ----------

def test_reset_with_code_sets_password_and_issues_new_code(auth, teacher):
    _, code = teacher
    new_code = auth.reset_with_recovery_code("pytest_sec", code.lower().replace("-", " "), NEW_PASSWORD)
    assert new_code != code
    assert auth.authenticate("pytest_sec", NEW_PASSWORD) is not None


def test_recovery_code_is_one_time(auth, teacher):
    _, code = teacher
    auth.reset_with_recovery_code("pytest_sec", code, NEW_PASSWORD)
    with pytest.raises(AuthError):
        auth.reset_with_recovery_code("pytest_sec", code, "third-password-x")


def test_reset_clears_lock(auth, teacher):
    fail(auth, times=5)
    _, code = teacher
    with pytest.raises(AuthLocked):  # заблоковано — навіть правильний код не пройде
        auth.reset_with_recovery_code("pytest_sec", code, NEW_PASSWORD)


def test_reset_clears_lock_after_expiry(auth, teacher, clock, session):
    fail(auth, times=5)
    clock.advance(31)
    auth.reset_with_recovery_code("pytest_sec", teacher[1], NEW_PASSWORD)
    row = session.get(Teacher, teacher[0].id)
    assert (row.failed_attempts, row.locked_until) == (0, None)


def test_reset_wrong_code_counts_and_locks(auth, teacher, session):
    for _ in range(5):
        with pytest.raises(AuthError) as info:
            auth.reset_with_recovery_code("pytest_sec", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)
        assert info.value.persist is True
    with pytest.raises(AuthLocked):
        auth.reset_with_recovery_code("pytest_sec", teacher[1], NEW_PASSWORD)


def test_reset_unknown_user_same_error_and_throttled(auth, teacher):
    with pytest.raises(AuthError) as ghost:
        auth.reset_with_recovery_code("pytest_ghost", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)
    with pytest.raises(AuthError) as real:
        auth.reset_with_recovery_code("pytest_sec", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)
    assert str(ghost.value) == str(real.value)
    for _ in range(4):
        with pytest.raises(AuthError):
            auth.reset_with_recovery_code("pytest_ghost", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)
    with pytest.raises(AuthLocked):
        auth.reset_with_recovery_code("pytest_ghost", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)


def test_reset_without_stored_code_fails_generically(auth, teacher, session):
    session.get(Teacher, teacher[0].id).recovery_code_hash = None
    with pytest.raises(AuthError):
        auth.reset_with_recovery_code("pytest_sec", teacher[1], NEW_PASSWORD)


def test_reset_rejects_short_password_without_burning_attempt(auth, teacher, session):
    with pytest.raises(AuthError, match="щонайменше 8"):
        auth.reset_with_recovery_code("pytest_sec", teacher[1], "short")
    assert session.get(Teacher, teacher[0].id).failed_attempts == 0


# ---------- адмін-скидання й логи ----------

def test_admin_reset_clears_lock_and_issues_code(auth, teacher, session):
    fail(auth, times=5)
    code = auth.admin_reset_password("pytest_sec", NEW_PASSWORD)
    row = session.get(Teacher, teacher[0].id)
    assert (row.failed_attempts, row.locked_until) == (0, None)
    assert auth.authenticate("pytest_sec", NEW_PASSWORD) is not None
    assert re.match(r"^[A-Z0-9-]{19}$", code)


def test_admin_reset_unknown_user(auth):
    with pytest.raises(AuthError):
        auth.admin_reset_password("pytest_nobody", NEW_PASSWORD)


def test_logs_never_contain_secrets(auth, teacher, caplog):
    caplog.set_level("DEBUG")
    fail(auth, times=2)
    fail(auth, "pytest_ghost")
    with pytest.raises(AuthError):
        auth.reset_with_recovery_code("pytest_sec", "AAAA-AAAA-AAAA-AAAA", NEW_PASSWORD)
    with pytest.raises(AuthError):
        auth.change_password(teacher[0].id, "wrong-current", NEW_PASSWORD)
    text = caplog.text
    assert f"failed login for teacher id={teacher[0].id}" in text
    assert "failed login for unknown user" in text
    assert "pytest_sec" not in text and "pytest_ghost" not in text
    for secret in ("wrong-password", "wrong-current", NEW_PASSWORD, PASSWORD, teacher[1], "argon2"):
        assert secret not in text


def test_ensure_recovery_code_issues_once(auth, teacher, session):
    row = session.get(Teacher, teacher[0].id)
    row.recovery_code_hash = None
    code = auth.ensure_recovery_code(teacher[0].id)
    assert code and re.match(r"^[A-Z0-9-]{19}$", code)
    assert row.recovery_code_hash.startswith("$argon2")
    assert auth.ensure_recovery_code(teacher[0].id) is None
    auth.reset_with_recovery_code("pytest_sec", code, NEW_PASSWORD)


def test_ensure_recovery_code_none_if_present_or_unknown(auth, teacher):
    assert auth.ensure_recovery_code(teacher[0].id) is None
    assert auth.ensure_recovery_code(999_999_999) is None

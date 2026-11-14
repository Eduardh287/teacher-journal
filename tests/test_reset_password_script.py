"""scripts/reset_password.py: пароль лише через getpass, ніколи з аргументів і не в виводі."""
import importlib.util
import subprocess
import sys

import pytest

from journal.config import PROJECT_ROOT
from journal.models import Teacher
from journal.services.auth_service import AuthService

SCRIPT = PROJECT_ROOT / "scripts" / "reset_password.py"
NEW_PASSWORD = "brand-new-secret-pw"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("reset_password_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prompts(*answers):
    queue = list(answers)
    return lambda prompt: queue.pop(0)


def test_resets_password_and_prints_new_code_only(script, session, capsys):
    auth = AuthService(session)
    auth.register("pytest_cli", "old-password-1", "Скрипт Тест")
    output = []
    code = script.main(
        ["pytest_cli"],
        ask_password=_prompts(NEW_PASSWORD, NEW_PASSWORD),
        run=lambda action: action(AuthService(session)),
        out=output.append,
    )
    assert code == 0
    text = "\n".join(output)
    assert NEW_PASSWORD not in text and "argon2" not in text
    assert "код відновлення" in text
    assert auth.authenticate("pytest_cli", NEW_PASSWORD) is not None


def test_mismatch_changes_nothing(script, session):
    AuthService(session).register("pytest_cli2", "old-password-1", "Скрипт Тест")
    output = []
    code = script.main(
        ["pytest_cli2"],
        ask_password=_prompts(NEW_PASSWORD, "different-password"),
        run=lambda action: action(AuthService(session)),
        out=output.append,
    )
    assert code == 1
    assert AuthService(session).authenticate("pytest_cli2", "old-password-1") is not None


def test_unknown_user_and_short_password_reported(script, session):
    output = []
    run = lambda action: action(AuthService(session))  # noqa: E731
    assert script.main(["pytest_nobody"], _prompts("long-enough-pw", "long-enough-pw"), run, output.append) == 1
    AuthService(session).register("pytest_cli3", "old-password-1", "Скрипт Тест")
    assert script.main(["pytest_cli3"], _prompts("short", "short"), run, output.append) == 1


def test_clears_lock(script, session):
    auth = AuthService(session)
    auth.register("pytest_cli4", "old-password-1", "Скрипт Тест")
    for _ in range(5):
        auth.authenticate("pytest_cli4", "wrong")
    script.main(
        ["pytest_cli4"], _prompts(NEW_PASSWORD, NEW_PASSWORD),
        lambda action: action(AuthService(session)), lambda text: None,
    )
    row = session.query(Teacher).filter_by(username="pytest_cli4").one()
    assert (row.failed_attempts, row.locked_until) == (0, None)


def test_db_failure_does_not_leak_details(script):
    def broken(action):
        raise RuntimeError("postgresql://user:SECRET@host/db")

    output = []
    code = script.main(["x"], _prompts("long-enough-pw", "long-enough-pw"), broken, output.append)
    assert code == 2
    assert "SECRET" not in "\n".join(output)


@pytest.mark.parametrize(
    "extra", [["--password", NEW_PASSWORD], [NEW_PASSWORD], ["-p", NEW_PASSWORD]]
)
def test_refuses_password_from_argv(extra):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "pytest_cli", *extra],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert result.returncode != 0
    assert NEW_PASSWORD not in result.stdout
    assert NEW_PASSWORD not in result.stderr

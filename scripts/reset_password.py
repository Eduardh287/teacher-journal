r"""Скидання пароля викладачки (лише для автора, запускається локально на її комп'ютері).

    python scripts\reset_password.py <логін>

Новий пароль запитується двічі через getpass і НІКОЛИ не приймається аргументом командного рядка.
Працює в режимі розробки (DATABASE_URL з .env) і у встановленій версії
(JOURNAL_EMBEDDED=1 — тоді запускається вбудований PostgreSQL). Закрийте журнал перед запуском.
Скрипт знімає блокування й виводить новий код відновлення (старий перестає діяти).
"""
import argparse
import getpass
import sys
from collections.abc import Callable
from typing import Any
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from journal.services.auth_service import AuthError, AuthService  # noqa: E402


def _run_in_db(action: Callable[[AuthService], Any]) -> Any:
    from journal.db import session_scope

    with session_scope() as session:
        return action(AuthService(session))


class _QuietParser(argparse.ArgumentParser):
    """Не повторює у повідомленні про помилку те, що ввели (раптом це пароль)."""

    def error(self, message: str):
        self.exit(
            2,
            "Помилка аргументів. Використання: reset_password.py <логін>\n"
            "Пароль у командному рядку не приймається - його буде запитано окремо.\n",
        )


def main(
    argv: list[str] | None = None,
    ask_password: Callable[[str], str] = getpass.getpass,
    run: Callable[[Callable[[AuthService], Any]], Any] = _run_in_db,
    out: Callable[[str], None] = print,
) -> int:
    parser = _QuietParser(
        description="Скидання пароля викладачки. Пароль вводиться лише інтерактивно."
    )
    parser.add_argument("username", help="логін викладачки")
    args = parser.parse_args(argv)  # будь-які інші аргументи (зокрема пароль) — помилка

    try:
        exists = run(lambda auth: auth.has_teacher(args.username))
    except Exception as error:
        out(f"Не вдалося зв'язатися з базою даних ({type(error).__name__}). Журнал закрито?")
        return 2
    if not exists:
        out("Користувача не знайдено.")
        return 1

    password = ask_password("Новий пароль: ")
    if password != ask_password("Повторіть пароль: "):
        out("Паролі не збігаються. Нічого не змінено.")
        return 1
    try:
        code = run(lambda auth: auth.admin_reset_password(args.username, password))
    except AuthError as error:
        out(f"Помилка: {error}")
        return 1
    except Exception as error:
        # Без деталей: у тексті помилки БД може бути рядок підключення.
        out(f"Не вдалося зв'язатися з базою даних ({type(error).__name__}). Журнал закрито?")
        return 2
    out("Пароль змінено, блокування знято.")
    out(f"Новий код відновлення (запишіть і передайте викладачці): {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

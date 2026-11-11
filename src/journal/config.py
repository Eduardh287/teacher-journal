"""Налаштування застосунку. Рядки підключення до БД читаються з файлу .env (не в git)."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

_SETUP_HINT = "Запустіть scripts/setup_dev_db.ps1 або скопіюйте .env.example у .env."


def database_url() -> str:
    """Підключення до робочої бази застосунку."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL не задано. {_SETUP_HINT}")
    return url


def get_test_database_url() -> str:
    """Підключення до окремої бази для тестів. Ім'я бази мусить закінчуватись на «_test»."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(f"TEST_DATABASE_URL не задано. {_SETUP_HINT}")
    db_name = make_url(url).database or ""
    app_url = os.getenv("DATABASE_URL")
    if not db_name.endswith("_test") or (app_url and make_url(app_url).database == db_name):
        raise RuntimeError(
            "TEST_DATABASE_URL має вказувати на окрему базу з назвою *_test — тести не запускаються."
        )
    return url

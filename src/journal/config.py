"""Налаштування застосунку. Рядки підключення до БД читаються з файлу .env (не в git)."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

_SETUP_HINT = "Запустіть scripts/setup_dev_db.ps1 або скопіюйте .env.example у .env."


def database_url() -> str:
    """Підключення до робочої бази застосунку."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL не задано. {_SETUP_HINT}")
    return url


def test_database_url() -> str:
    """Підключення до окремої бази для тестів. Ніколи не збігається з робочою."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(f"TEST_DATABASE_URL не задано. {_SETUP_HINT}")
    if url == os.getenv("DATABASE_URL"):
        raise RuntimeError("TEST_DATABASE_URL збігається з DATABASE_URL — тести не запускаються.")
    return url

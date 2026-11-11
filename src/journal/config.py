"""Налаштування застосунку. Рядок підключення до БД читається з файлу .env (не в git)."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL не задано. Скопіюйте .env.example у .env і вкажіть пароль "
            "(або запустіть scripts/setup_dev_db.ps1)."
        )
    return url

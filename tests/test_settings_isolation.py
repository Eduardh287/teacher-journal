"""Фікстура ізоляції справді переспрямовує QSettings у тимчасову папку."""
from pathlib import Path

from journal.ui.theme import app_settings


def test_app_settings_are_isolated(tmp_path):
    assert tmp_path in Path(app_settings().fileName()).parents

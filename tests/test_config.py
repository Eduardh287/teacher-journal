"""Тести journal.config.get_test_database_url (змінні оточення підміняються через monkeypatch)."""
import pytest

from journal.config import get_test_database_url

APP_URL = "postgresql+psycopg://u:p@localhost:5432/journal"


@pytest.fixture(autouse=True)
def app_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", APP_URL)


def test_missing_test_url_raises(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_test_database_url()


def test_name_without_test_suffix_raises(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/journal_dev")
    with pytest.raises(RuntimeError):
        get_test_database_url()


def test_same_database_as_app_raises(monkeypatch):
    same = "postgresql+psycopg://u:p@localhost:5432/journal_test"
    monkeypatch.setenv("DATABASE_URL", same)
    monkeypatch.setenv("TEST_DATABASE_URL", same)
    with pytest.raises(RuntimeError):
        get_test_database_url()


def test_valid_test_url_returned_unchanged(monkeypatch):
    url = "postgresql+psycopg://u:p@localhost:5432/journal_test"
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    assert get_test_database_url() == url

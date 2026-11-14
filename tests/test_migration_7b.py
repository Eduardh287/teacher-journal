"""Міграція етапу 7b: вгору й вниз на journal_test (після тесту схема знову на head)."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from journal.config import PROJECT_ROOT, get_test_database_url

REVISION = "b5d2e8f1a3c7"
PREVIOUS = "a7c41d9e5b02"
NEW_COLUMNS = {"failed_attempts", "locked_until", "recovery_code_hash"}


def _config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = get_test_database_url()
    cfg.attributes["skip_logging_config"] = True
    return cfg


def _teacher_columns() -> dict:
    engine = create_engine(get_test_database_url())
    try:
        return {c["name"]: c for c in inspect(engine).get_columns("teachers")}
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_cleanly(engine):
    cfg = _config()
    engine.dispose()  # відпускаємо з'єднання з пулу, щоб DDL не чекав блокувань
    try:
        command.downgrade(cfg, PREVIOUS)
        assert not NEW_COLUMNS & set(_teacher_columns())
        command.upgrade(cfg, "head")
        columns = _teacher_columns()
        assert NEW_COLUMNS <= set(columns)
        assert columns["failed_attempts"]["nullable"] is False
        assert columns["locked_until"]["nullable"] is True
        assert columns["recovery_code_hash"]["nullable"] is True
        assert columns["locked_until"]["type"].timezone is True
    finally:
        command.upgrade(cfg, "head")


def test_head_is_this_revision_or_later():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(script.get_heads()) == 1

"""Міграція «колір рядка учня»: вгору й вниз на journal_test (після тесту схема знову на head)."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from journal.config import PROJECT_ROOT, get_test_database_url

REVISION = "c3f8a1d27e64"
PREVIOUS = "b5d2e8f1a3c7"


def _config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = get_test_database_url()
    cfg.attributes["skip_logging_config"] = True
    return cfg


def _student_schema() -> tuple[dict, set]:
    engine = create_engine(get_test_database_url())
    try:
        insp = inspect(engine)
        columns = {c["name"]: c for c in insp.get_columns("students")}
        checks = {c["name"] for c in insp.get_check_constraints("students")}
        return columns, checks
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_cleanly(engine):
    cfg = _config()
    engine.dispose()
    try:
        command.downgrade(cfg, PREVIOUS)
        columns, checks = _student_schema()
        assert "row_color" not in columns and "ck_students_row_color" not in checks
        command.upgrade(cfg, "head")
        columns, checks = _student_schema()
        assert columns["row_color"]["nullable"] is True
        assert "ck_students_row_color" in checks
    finally:
        command.upgrade(cfg, "head")


def test_revision_follows_previous():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(script.get_heads()) == 1

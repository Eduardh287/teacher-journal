"""Інтеграційні тести резервних копій: ЛИШЕ база TEST_DATABASE_URL (journal_test).

Відновлення стирає схему public, тому сервіс тут отримує URL тестової бази й ніякої іншої.
Після тесту база повертається до alembic head (її робить сам restore; перевіряємо це).
"""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from journal import db, embedded_db
from journal.config import get_test_database_url
from journal.services.backup_service import BackupError, BackupService, RestoreFailed

PG_BIN = embedded_db.pgsql_dir() / "bin"

pytestmark = pytest.mark.skipif(
    not (PG_BIN / "pg_dump.exe").exists() and shutil.which("pg_dump") is None,
    reason="pg_dump не знайдено",
)

PROBE = "bk_probe_teacher"
CHANGED = "bk_changed_teacher"


def usernames(engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT username FROM teachers"))}


def add_teacher(engine, username: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO teachers (username, password_hash, full_name) VALUES (:u, 'x', 'Тест')"),
            {"u": username},
        )


@pytest.fixture
def test_engine():
    """Окремий engine до journal_test (не залежить від транзакційної фікстури session)."""
    url = get_test_database_url()
    assert url.rsplit("/", 1)[-1].split("?")[0].endswith("_test")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM teachers WHERE username IN (:a, :b)"), {"a": PROBE, "b": CHANGED})
        engine.dispose()


def make_service(tmp_path: Path, folder_name: str) -> BackupService:
    folder = tmp_path / folder_name
    return BackupService(
        get_test_database_url(),
        pg_bin=PG_BIN,
        default_dir=folder,
        dispose_engine=lambda: db.get_engine().dispose(),
    )


@pytest.mark.parametrize("folder_name", ["backups", "резервні копії"])
def test_dump_modify_restore_roundtrip(tmp_path, test_engine, folder_name):
    service = make_service(tmp_path, folder_name)  # друга папка — кирилична
    add_teacher(test_engine, PROBE)
    backup = service.create_backup("manual")
    assert backup.parent.name == folder_name and backup.stat().st_size > 0

    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM teachers WHERE username = :u"), {"u": PROBE})
    add_teacher(test_engine, CHANGED)
    assert usernames(test_engine) == {CHANGED}

    info = service.restore(backup)
    test_engine.dispose()

    assert usernames(test_engine) == {PROBE}
    assert list(backup.parent.glob("*_before-restore.dump"))
    assert embedded_db.current_revision(get_test_database_url()) == embedded_db.script_head()
    assert info.revision == embedded_db.script_head()


def test_restore_failure_is_rolled_back_to_previous_state(tmp_path, test_engine):
    service = make_service(tmp_path, "backups")
    add_teacher(test_engine, PROBE)
    good = service.create_backup("manual")
    add_teacher(test_engine, CHANGED)  # поточний стан, який має вціліти після невдалого відновлення

    broken = good.with_name("journal_2026-01-01_00-00-00_manual.dump")
    data = good.read_bytes()
    broken.write_bytes(data[: len(data) // 2] + b"\x00garbage" * 50)  # обрізана копія
    # inspect може пройти (TOC цілий), а завантаження — впасти; у будь-якому разі стан не втрачається
    with pytest.raises(BackupError) as caught:
        service.restore(broken)
    if isinstance(caught.value, RestoreFailed):
        assert caught.value.rolled_back
    test_engine.dispose()
    assert usernames(test_engine) == {PROBE, CHANGED}
    assert embedded_db.current_revision(get_test_database_url()) == embedded_db.script_head()

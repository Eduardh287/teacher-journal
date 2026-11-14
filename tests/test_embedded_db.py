"""Тести логіки вбудованої БД (шляхи, порти, секрет, режим). Справжній сервер не запускається."""
import hashlib
import sys
from pathlib import Path

import pytest

from journal import embedded_db as e


def test_is_ascii():
    assert e.is_ascii(r"C:\Users\admin")
    assert not e.is_ascii(r"C:\Users\Адмін")


def test_ascii_path_used_directly():
    path = Path(r"C:\data\journal")
    assert e.ascii_safe(path, shorten=lambda p: pytest.fail("не мав викликатись")) == path


def test_cyrillic_path_uses_short_form():
    short = e.ascii_safe(Path(r"C:\Users\Адмін\x"), shorten=lambda p: r"C:\USERS\744C~1\x")
    assert short == Path(r"C:\USERS\744C~1\x")


def test_cyrillic_path_without_short_name_returns_none():
    assert e.ascii_safe(Path(r"C:\Users\Адмін\x"), shorten=lambda p: p) is None


def test_fallback_root_is_ascii_and_stable():
    digest = hashlib.sha1("Адмін".encode("utf-8")).hexdigest()[:12]
    root = e.fallback_root("Адмін", r"C:\ProgramData")
    assert root == Path(r"C:\ProgramData") / "teacher-journal" / digest
    assert e.is_ascii(root)


@pytest.fixture
def fake_ascii(monkeypatch):
    """tmp_path може сам містити кирилицю; «не-ASCII» вважаємо лише папку «дані»."""
    monkeypatch.setattr(e, "is_ascii", lambda p: "дані" not in str(p))
    monkeypatch.setattr(e, "_restrict_to_current_user", lambda p: None)


def test_layout_direct_branch(tmp_path, fake_ascii):
    layout = e.resolve_layout(tmp_path / "data")
    assert layout.branch == "direct"
    assert layout.pgdata == tmp_path / "data" / "pgdata"
    assert layout.logs.is_dir()


def test_layout_short_branch(tmp_path, fake_ascii):
    ascii_dir = tmp_path / "short"
    layout = e.resolve_layout(tmp_path / "дані", shorten=lambda p: str(ascii_dir))
    assert layout.branch == "short"
    assert layout.root == ascii_dir


def test_layout_fallback_branch(tmp_path, fake_ascii):
    fallback = tmp_path / "pd" / "abc"
    layout = e.resolve_layout(tmp_path / "дані", shorten=lambda p: p, fallback=fallback)
    assert layout.branch == "fallback"
    assert layout.root == fallback and fallback.is_dir()


def test_requested_root_prefers_override(monkeypatch):
    monkeypatch.setenv("JOURNAL_DATA_DIR", r"C:\scratch")
    assert e.requested_root() == Path(r"C:\scratch")
    monkeypatch.delenv("JOURNAL_DATA_DIR")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\L")
    assert e.requested_root() == Path(r"C:\L") / "teacher-journal"


def test_secret_is_random_and_persisted(tmp_path):
    first = e.generate_secret()
    assert len(first) == 32 and first.isalnum() and first != e.generate_secret()
    file = tmp_path / "db.secret"
    created = e.load_or_create_secret(file)
    assert file.read_text() == created
    assert e.load_or_create_secret(file) == created


def test_pick_port_defaults_to_first():
    assert e.pick_port(None, is_free=lambda p: True) == 54329


def test_pick_port_prefers_saved_when_free():
    assert e.pick_port(54333, is_free=lambda p: True) == 54333


def test_pick_port_skips_busy():
    busy = {54329, 54330}
    assert e.pick_port(None, is_free=lambda p: p not in busy) == 54331
    assert e.pick_port(54329, is_free=lambda p: p not in busy) == 54331


def test_pick_port_ignores_saved_out_of_range():
    assert e.pick_port(5432, is_free=lambda p: True) == 54329


def test_pick_port_all_busy_raises():
    with pytest.raises(e.EmbeddedDbError):
        e.pick_port(None, is_free=lambda p: False)


def test_read_saved_port(tmp_path):
    file = tmp_path / "port"
    assert e.read_saved_port(file) is None
    file.write_text("54331")
    assert e.read_saved_port(file) == 54331
    file.write_text("junk")
    assert e.read_saved_port(file) is None


def test_build_url():
    assert e.build_url("pw", 54329) == "postgresql+psycopg://journal:pw@127.0.0.1:54329/journal"


def test_bundled_mode(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JOURNAL_EMBEDDED", raising=False)
    assert not e.is_bundled_mode()
    monkeypatch.setenv("JOURNAL_EMBEDDED", "1")
    assert e.is_bundled_mode()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    assert not e.is_bundled_mode()
    monkeypatch.delenv("JOURNAL_EMBEDDED")
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert e.is_bundled_mode()


def test_init_cluster_keeps_password_off_command_line_and_removes_pwfile(tmp_path, monkeypatch):
    layout = e.resolve_layout(tmp_path / "root")
    pg = tmp_path / "pg"
    (pg / "bin").mkdir(parents=True)
    (pg / "bin" / "pg_ctl.exe").write_text("")
    seen = {}

    def fake_run(cmd, timeout=120, **kw):
        pwfile = next(a for a in cmd if a.startswith("--pwfile=")).split("=", 1)[1]
        seen["cmd"] = cmd
        seen["pw_in_file"] = Path(pwfile).read_text()
        seen["pwfile"] = pwfile

        class R:
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr(e, "_run", fake_run)
    db = e.EmbeddedDb(layout, pg_root=pg)
    db.init_cluster("SECRETSECRET")
    assert "SECRETSECRET" not in " ".join(seen["cmd"])
    assert seen["pw_in_file"] == "SECRETSECRET"
    assert not Path(seen["pwfile"]).exists()


def test_initdb_failure_raises_without_leaking_password(tmp_path, monkeypatch):
    layout = e.resolve_layout(tmp_path / "root")
    pg = tmp_path / "pg"
    (pg / "bin").mkdir(parents=True)
    (pg / "bin" / "pg_ctl.exe").write_text("")

    class R:
        returncode = 1
        stderr = "boom"

    monkeypatch.setattr(e, "_run", lambda *a, **k: R())
    with pytest.raises(e.EmbeddedDbError) as err:
        e.EmbeddedDb(layout, pg_root=pg).init_cluster("SECRETSECRET")
    assert "SECRETSECRET" not in str(err.value)


def test_missing_pgsql_dir_gives_clear_error(tmp_path):
    layout = e.resolve_layout(tmp_path / "root")
    with pytest.raises(e.EmbeddedDbError):
        e.EmbeddedDb(layout, pg_root=tmp_path / "nope")


# ---------------------------------------------------------------- копія перед міграцією (етап 7a)

def _fake_service(monkeypatch, created, error=None):
    from journal.services import backup_service

    class FakeService:
        def __init__(self, url, **kw):
            created.append(("init", kw["default_dir"]))

        def create_backup(self, kind, **kw):
            if error:
                raise error
            created.append((kind, kw))
            return Path("x.dump")

    monkeypatch.setattr(backup_service, "BackupService", FakeService)


def test_backup_before_migration_for_old_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("JOURNAL_DATA_DIR", str(tmp_path))
    created = []
    _fake_service(monkeypatch, created)
    monkeypatch.setattr(e, "current_revision", lambda url: "old")
    monkeypatch.setattr(e, "script_head", lambda: "new")
    e.backup_before_migration("postgresql+psycopg://u:p@h/db")
    assert ("before-migration", {"default_folder_only": True}) in created
    assert created[0] == ("init", tmp_path / "backups")


@pytest.mark.parametrize("revision", [None, "new"])
def test_no_backup_for_fresh_or_current_schema(monkeypatch, revision):
    created = []
    _fake_service(monkeypatch, created)
    monkeypatch.setattr(e, "current_revision", lambda url: revision)
    monkeypatch.setattr(e, "script_head", lambda: "new")
    e.backup_before_migration("postgresql+psycopg://u:p@h/db")
    assert created == []


def test_no_alembic_table_means_no_backup(monkeypatch):
    created = []
    _fake_service(monkeypatch, created)

    def boom(url):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(e, "current_revision", boom)
    e.backup_before_migration("postgresql+psycopg://u:p@h/db")
    assert created == []


def test_failed_backup_blocks_migration(monkeypatch):
    from journal.services.backup_service import BackupError

    _fake_service(monkeypatch, [], error=BackupError("Диск повний."))
    monkeypatch.setattr(e, "current_revision", lambda url: "old")
    monkeypatch.setattr(e, "script_head", lambda: "new")
    with pytest.raises(e.EmbeddedDbError, match="оновлення не виконано"):
        e.backup_before_migration("postgresql+psycopg://u:p@h/db")

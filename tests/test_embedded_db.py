"""Тести логіки вбудованої БД (шляхи, порти, секрет, режим). Справжній сервер не запускається."""
import hashlib
import sys
from pathlib import Path

import psycopg
import psycopg.errors
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


def test_init_cluster_keeps_password_off_command_line_and_removes_pwfile(tmp_path, monkeypatch, fake_ascii):
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


def test_initdb_failure_raises_without_leaking_password(tmp_path, monkeypatch, fake_ascii):
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


def test_missing_pgsql_dir_gives_clear_error(tmp_path, fake_ascii):
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
        raise psycopg.errors.UndefinedTable("relation does not exist")

    monkeypatch.setattr(e, "current_revision", boom)
    e.backup_before_migration("postgresql+psycopg://u:p@h/db")
    assert created == []


@pytest.mark.parametrize("error", [RuntimeError("x"), psycopg.OperationalError("down")])
def test_other_errors_block_migration(monkeypatch, error):
    created = []
    _fake_service(monkeypatch, created)

    def boom(url):
        raise error

    monkeypatch.setattr(e, "current_revision", boom)
    with pytest.raises(e.EmbeddedDbError, match="оновлення не виконано"):
        e.backup_before_migration("postgresql+psycopg://u:p@h/db")
    assert created == []


def test_failed_backup_blocks_migration(monkeypatch):
    from journal.services.backup_service import BackupError

    _fake_service(monkeypatch, [], error=BackupError("Диск повний."))
    monkeypatch.setattr(e, "current_revision", lambda url: "old")
    monkeypatch.setattr(e, "script_head", lambda: "new")
    with pytest.raises(e.EmbeddedDbError, match="оновлення не виконано"):
        e.backup_before_migration("postgresql+psycopg://u:p@h/db")


# ---------------------------------------------------------------- етап 8b

@pytest.fixture
def fake_pg(tmp_path, fake_ascii):
    """Layout + каталог pgsql із фіктивним pg_ctl.exe (процеси не запускаються)."""
    layout = e.resolve_layout(tmp_path / "root")
    pg = tmp_path / "pg"
    (pg / "bin").mkdir(parents=True)
    (pg / "bin" / "pg_ctl.exe").write_text("")
    return layout, pg


class _R:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


# E1: icacls за повним шляхом, збій -> EmbeddedDbError

def test_icacls_uses_full_path_and_succeeds(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _R(0)

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(e.subprocess, "run", fake_run)
    e._restrict_to_current_user(tmp_path)
    assert seen["cmd"][0] == str(Path(r"C:\Windows") / "System32" / "icacls.exe")


@pytest.mark.parametrize("outcome", [_R(5), OSError("no icacls"), e.subprocess.TimeoutExpired("icacls", 30)])
def test_icacls_failure_fails_closed(monkeypatch, tmp_path, outcome):
    def fake_run(cmd, **kw):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(e.subprocess, "run", fake_run)
    with pytest.raises(e.EmbeddedDbError):
        e._restrict_to_current_user(tmp_path)


def test_fallback_layout_fails_when_icacls_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "is_ascii", lambda p: "дані" not in str(p))
    monkeypatch.setattr(e.subprocess, "run", lambda *a, **k: _R(1))
    with pytest.raises(e.EmbeddedDbError):
        e.resolve_layout(tmp_path / "дані", shorten=lambda p: p, fallback=tmp_path / "pd")


# E3: помилки -> EmbeddedDbError

def test_run_timeout_becomes_embedded_error(monkeypatch):
    def boom(*a, **k):
        raise e.subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(e.subprocess, "run", boom)
    with pytest.raises(e.EmbeddedDbError):
        e._run(["pg_ctl.exe", "status"])


def test_psycopg_error_in_ensure_database_is_wrapped(fake_pg, monkeypatch):
    layout, pg = fake_pg

    def boom(*a, **k):
        raise psycopg.OperationalError("password authentication failed for user journal SECRET")

    monkeypatch.setattr(psycopg, "connect", boom)
    with pytest.raises(e.EmbeddedDbError) as err:
        e.EmbeddedDb(layout, pg_root=pg).ensure_database("pw", 54329)
    assert "SECRET" not in str(err.value)


def test_alembic_error_is_wrapped(monkeypatch):
    from alembic import command

    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(command, "upgrade", boom)
    with pytest.raises(e.EmbeddedDbError) as err:
        e.upgrade_schema("postgresql+psycopg://u:p@h/db")
    assert "secret detail" not in str(err.value)


# E4: порожній db.secret при ініціалізованому кластері

@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_missing_or_empty_secret_with_cluster_is_an_error(fake_pg, content):
    layout, pg = fake_pg
    layout.pgdata.mkdir()
    (layout.pgdata / "PG_VERSION").write_text("17")
    if content is not None:
        layout.secret_file.write_text(content)
    with pytest.raises(e.EmbeddedDbError, match="db.secret"):
        e.EmbeddedDb(layout, pg_root=pg).ensure_running()
    assert not layout.secret_file.exists() if content is None else layout.secret_file.read_text() == content


def test_secret_present(tmp_path):
    f = tmp_path / "s"
    assert not e.secret_present(f)
    f.write_text("")
    assert not e.secret_present(f)
    f.write_text("abc")
    assert e.secret_present(f)


# E5: pg_ctl start

class _Pg:
    """Збирає виклики subprocess.run і підміняє _run (status/stop)."""

    def __init__(self, monkeypatch, start_code=0, status_codes=(3,)):
        self.calls = []
        self.status_codes = list(status_codes)
        self.start_code = start_code

        def fake_subprocess_run(cmd, **kw):
            self.calls.append((cmd, kw))
            if isinstance(self.start_code, BaseException):
                raise self.start_code
            return _R(self.start_code)

        def fake_run(cmd, timeout=120, **kw):
            self.calls.append((cmd, {"timeout": timeout}))
            if "status" in cmd:
                return _R(self.status_codes.pop(0) if len(self.status_codes) > 1 else self.status_codes[0])
            return _R(0)

        monkeypatch.setattr(e.subprocess, "run", fake_subprocess_run)
        monkeypatch.setattr(e, "_run", fake_run)

    def commands(self, word):
        return [c for c, _ in self.calls if word in c]


def test_start_timeout_is_60_seconds(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch)
    port = e.EmbeddedDb(layout, pg_root=pg).start()
    start_cmd = fake.commands("start")[0]
    assert e.START_TIMEOUT_SEC == 60
    assert start_cmd[start_cmd.index("-t") + 1] == "60"
    assert 54329 <= port <= 54339


def test_start_nonzero_but_status_running_is_ok(fake_pg, monkeypatch):
    layout, pg = fake_pg
    _Pg(monkeypatch, start_code=1, status_codes=(0,))
    assert e.EmbeddedDb(layout, pg_root=pg).start()


@pytest.mark.parametrize("start_code", [1, e.subprocess.TimeoutExpired("pg_ctl", 90)])
def test_start_failure_with_server_down_raises(fake_pg, monkeypatch, start_code):
    layout, pg = fake_pg
    _Pg(monkeypatch, start_code=start_code, status_codes=(3,))
    with pytest.raises(e.EmbeddedDbError):
        e.EmbeddedDb(layout, pg_root=pg).start()


# C: stop лише якщо запустили ми

_EmbeddedDbClass = e.EmbeddedDb

def _prepare_running(layout, monkeypatch, fake):
    layout.secret_file.write_text("pw")
    layout.pgdata.mkdir(exist_ok=True)
    (layout.pgdata / "PG_VERSION").write_text("17")
    monkeypatch.setattr(_EmbeddedDbClass, "ensure_database", lambda self, pw, port: None)


def test_reused_server_is_not_stopped(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(0,))
    _prepare_running(layout, monkeypatch, fake)
    (layout.pgdata / "postmaster.pid").write_text("1\nx\n0\n54331\n")
    db = e.EmbeddedDb(layout, pg_root=pg)
    url = db.ensure_running()
    assert url.endswith(":54331/journal") and db.port == 54331
    assert not db.started_by_us
    db.stop()
    assert fake.commands("stop") == []


def test_started_server_is_stopped(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(3, 0))  # до запуску не працює, потім працює
    _prepare_running(layout, monkeypatch, fake)
    db = e.EmbeddedDb(layout, pg_root=pg)
    db.ensure_running()
    assert db.started_by_us and db.url
    db.stop()
    assert len(fake.commands("stop")) == 1 and db.url is None and not db.started_by_us
    db.stop()  # повторно — нічого
    assert len(fake.commands("stop")) == 1



def test_error_path_does_not_stop_a_foreign_server(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(0,))
    monkeypatch.setattr(e, "resolve_layout", lambda: layout)
    monkeypatch.setattr(e, "EmbeddedDb", lambda lay: _EmbeddedDbClass(lay, pg_root=pg))
    monkeypatch.setattr(e, "_instance", None)

    def migration_fails(url):
        raise e.EmbeddedDbError("x")

    monkeypatch.setattr(e, "backup_before_migration", migration_fails)
    _prepare_running(layout, monkeypatch, fake)
    (layout.pgdata / "postmaster.pid").write_text("1\nx\n0\n54331\n")
    with pytest.raises(e.EmbeddedDbError):
        e.ensure_running()
    assert fake.commands("stop") == []


def test_force_stop_ignores_ownership(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(0, 3))  # працює, після stop — ні
    db = e.EmbeddedDb(layout, pg_root=pg)
    assert not db.started_by_us
    assert db.force_stop() is True
    assert len(fake.commands("stop")) == 1


def test_force_stop_when_nothing_runs_does_not_call_pg_ctl_stop(fake_pg, monkeypatch):
    layout, pg = fake_pg  # status 3 / немає postmaster.pid
    fake = _Pg(monkeypatch, status_codes=(3,))
    assert e.EmbeddedDb(layout, pg_root=pg).force_stop() is True
    assert fake.commands("stop") == []


def test_force_stop_reports_failure_when_server_still_runs(fake_pg, monkeypatch):
    layout, pg = fake_pg
    _Pg(monkeypatch, status_codes=(0,))
    assert e.EmbeddedDb(layout, pg_root=pg).force_stop() is False


def test_stop_when_server_already_gone_does_not_call_pg_ctl_stop(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(3,))
    db = e.EmbeddedDb(layout, pg_root=pg)
    db.started_by_us = True
    db.stop()
    assert fake.commands("stop") == [] and not db.started_by_us


def test_stop_server_for_installer(fake_pg, monkeypatch):
    layout, pg = fake_pg
    fake = _Pg(monkeypatch, status_codes=(0, 3))
    monkeypatch.setattr(e, "resolve_layout", lambda: layout)
    monkeypatch.setattr(e, "pgsql_dir", lambda: pg)
    assert e.stop_server_for_installer() is True  # кластера ще немає — нічого робити
    assert fake.commands("stop") == []
    layout.pgdata.mkdir()
    (layout.pgdata / "PG_VERSION").write_text("17")
    assert e.stop_server_for_installer() is True
    assert len(fake.commands("stop")) == 1


def test_ensure_database_failure_logs_sqlstate_but_not_message(fake_pg, monkeypatch, caplog):
    layout, pg = fake_pg

    def boom(*a, **k):
        raise psycopg.errors.InvalidPassword("password authentication failed SECRETTEXT")

    monkeypatch.setattr(psycopg, "connect", boom)
    with caplog.at_level("ERROR"), pytest.raises(e.EmbeddedDbError):
        e.EmbeddedDb(layout, pg_root=pg).ensure_database("pw", 54329)
    assert "28P01" in caplog.text and "SECRETTEXT" not in caplog.text


# running_port

def test_running_port_reads_postmaster_pid_then_port_file(fake_pg):
    layout, pg = fake_pg
    db = e.EmbeddedDb(layout, pg_root=pg)
    assert db.running_port() is None
    layout.port_file.write_text("54335")
    assert db.running_port() == 54335
    layout.pgdata.mkdir()
    (layout.pgdata / "postmaster.pid").write_text("123\nx\n0\n54337\n")
    assert db.running_port() == 54337
    (layout.pgdata / "postmaster.pid").write_text("junk")
    assert db.running_port() == 54335

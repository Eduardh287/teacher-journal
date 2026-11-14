"""Сервіс резервних копій на фейковому запускачі pg_dump/pg_restore (без PostgreSQL)."""
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from journal.services import backup_service as bs
from journal.services.backup_service import (
    BackupError,
    BackupService,
    BackupTooNewError,
    RestoreFailed,
    RunResult,
)

PASSWORD = "S3cretPassw0rdXYZ"
URL = f"postgresql+psycopg://journal:{PASSWORD}@127.0.0.1:54329/journal"
COPY_SQL = "COPY public.alembic_version (version_num) FROM stdin;\n{rev}\n\\.\n"


class FakeRunner:
    def __init__(self, revision="rev_a", dump_ok=True, list_ok=True, restore_results=None):
        self.revision = revision
        self.dump_ok = dump_ok
        self.list_ok = list_ok
        self.restore_results = list(restore_results or [])  # 0/1 для кожного повного pg_restore
        self.calls: list[tuple[list[str], dict]] = []
        self.timeouts: list[tuple[str, float | None]] = []
        self.raise_timeout = False
        self.dump_payload = b"PGDMP-fake"

    def __call__(self, args, *, env, stdin=None, stdout=None, timeout=None):
        self.calls.append((args, env))
        self.timeouts.append((Path(args[0]).stem, timeout))
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(args, timeout)
        tool = Path(args[0]).stem
        if tool == "pg_dump":
            if not self.dump_ok:
                stdout.write(b"partial")
                return RunResult(1, b"", f"boom {PASSWORD}")
            stdout.write(self.dump_payload)
            return RunResult(0, b"", "")
        if "--list" in args:
            return RunResult(0 if self.list_ok else 1, b"", "" if self.list_ok else "not a dump")
        if "--data-only" in args:
            return RunResult(0, COPY_SQL.format(rev=self.revision).encode(), "")
        code = self.restore_results.pop(0) if self.restore_results else 0
        return RunResult(code, b"", "restore failed" if code else "")

    def tools(self, name):
        return [c for c in self.calls if Path(c[0][0]).stem == name]


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 14, 10, 30, 5)

    def __call__(self):
        return self.value


def make(tmp_path, runner=None, backup_dir=None, **kw):
    runner = runner or FakeRunner()
    events = []
    service = BackupService(
        URL,
        pg_bin=tmp_path / "bin",
        default_dir=tmp_path / "default",
        backup_dir=backup_dir,
        runner=runner,
        now=kw.pop("now", Clock()),
        dispose_engine=lambda: events.append("dispose"),
        reset_schema=lambda url: events.append(("reset", url.database)),
        upgrade_schema=lambda url: events.append("upgrade"),
        known_revs=lambda: {"rev_a", "rev_b"},
        marker_path=tmp_path / "restore-in-progress",
        **kw,
    )
    service.events = events
    return service, runner


def test_file_name_and_atomic_rename(tmp_path):
    service, runner = make(tmp_path)
    path = service.create_backup("manual")
    assert path == tmp_path / "default" / "journal_2026-11-14_10-30-05_manual.dump"
    assert path.read_bytes() == b"PGDMP-fake"
    assert not list((tmp_path / "default").glob("*.part"))


def test_dump_goes_through_stdout_not_path(tmp_path):
    service, runner = make(tmp_path)
    path = service.create_backup("manual")
    args, _ = runner.tools("pg_dump")[0]
    assert not any(str(tmp_path) in a or ".dump" in a for a in args[1:])
    assert "-Fc" in args and "journal" in args


def test_failed_dump_leaves_no_files(tmp_path):
    service, _ = make(tmp_path, FakeRunner(dump_ok=False))
    with pytest.raises(BackupError):
        service.create_backup("manual")
    assert list((tmp_path / "default").iterdir()) == []


def test_same_second_does_not_overwrite(tmp_path):
    service, _ = make(tmp_path)
    first = service.create_backup("manual")
    second = service.create_backup("manual")
    assert first != second and first.exists() and second.exists()


def test_unknown_kind_rejected(tmp_path):
    service, _ = make(tmp_path)
    with pytest.raises(ValueError):
        service.create_backup("whatever")


def test_rotation_keeps_ten_newest_auto_only(tmp_path):
    clock = Clock()
    service, _ = make(tmp_path, now=clock)
    folder = tmp_path / "default"
    folder.mkdir()
    other = []
    for kind in ("manual", "before-restore", "before-migration"):
        clock.value -= timedelta(days=100)
        other.append(service.create_backup(kind))
    clock.value = datetime(2026, 11, 1, 8, 0, 0)
    for _ in range(13):
        clock.value += timedelta(days=1)
        service.create_backup("auto")
    autos = sorted(p.name for p in folder.glob("*_auto.dump"))
    assert len(autos) == 10
    assert autos[0].startswith("journal_2026-11-05")  # 3 найстарші видалено
    assert all(p.exists() for p in other)


def test_custom_folder_used_when_available(tmp_path):
    custom = tmp_path / "usb"
    custom.mkdir()
    service, _ = make(tmp_path, backup_dir=custom)
    path = service.create_backup("manual")
    assert path.parent == custom and not service.fallback_used


def test_unavailable_custom_folder_falls_back_to_default(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    service, _ = make(tmp_path, backup_dir=blocker / "sub")  # створити неможливо
    path = service.create_backup("manual")
    assert path.parent == tmp_path / "default"
    assert service.fallback_used


def test_before_migration_always_default_folder(tmp_path):
    custom = tmp_path / "usb"
    custom.mkdir()
    service, _ = make(tmp_path, backup_dir=custom)
    path = service.create_backup("before-migration", default_folder_only=True)
    assert path.parent == tmp_path / "default"


def test_list_backups_newest_first_and_ignores_foreign(tmp_path):
    service, _ = make(tmp_path)
    folder = tmp_path / "default"
    folder.mkdir()
    (folder / "journal_2026-01-01_00-00-00_manual.dump").write_bytes(b"x")
    (folder / "journal_2026-02-01_00-00-00_auto.dump").write_bytes(b"x")
    (folder / "random.dump").write_bytes(b"x")
    items = service.list_backups()
    assert [(i.created.month, i.kind) for i in items] == [(2, "auto"), (1, "manual")]


def test_list_backups_does_not_create_folder(tmp_path):
    service, _ = make(tmp_path)
    assert service.list_backups() == []
    assert not (tmp_path / "default").exists()


def test_parse_revision():
    assert bs.parse_revision(COPY_SQL.format(rev="abc123")) == "abc123"
    assert bs.parse_revision("-- nothing here") is None
    assert bs.parse_revision("COPY public.alembic_version (version_num) FROM stdin;\n\\.\n") is None


def test_inspect_reads_revision(tmp_path):
    service, _ = make(tmp_path)
    path = service.create_backup("auto")
    info = service.inspect(path)
    assert (info.revision, info.kind) == ("rev_a", "auto")
    assert info.created == datetime(2026, 11, 14, 10, 30, 5)


def test_newer_revision_refused(tmp_path):
    service, runner = make(tmp_path, FakeRunner(revision="from_the_future"))
    path = service.create_backup("manual")
    with pytest.raises(BackupTooNewError, match="іншою або новішою версією"):
        service.inspect(path)
    with pytest.raises(BackupTooNewError):
        service.restore(path)
    assert service.events == []  # нічого не стерто


def test_corrupt_file_refused(tmp_path):
    service, _ = make(tmp_path, FakeRunner(list_ok=False))
    path = tmp_path / "bad.dump"
    path.write_bytes(b"junk")
    with pytest.raises(BackupError):
        service.inspect(path)


def test_restore_success_sequence(tmp_path):
    service, runner = make(tmp_path)
    path = service.create_backup("manual")
    runner.calls.clear()
    info = service.restore(path)
    assert info.revision == "rev_a"
    # before-restore створено, схему стерто лише у базі цього сервісу, міграції виконано
    assert list((tmp_path / "default").glob("*_before-restore.dump"))
    assert service.events == ["dispose", ("reset", "journal"), "upgrade"]
    restore = [c for c in runner.tools("pg_restore") if "--single-transaction" in c[0]]
    assert len(restore) == 1
    args = restore[0][0]
    assert "--exit-on-error" in args and "--no-owner" in args and "--no-privileges" in args
    assert not any(str(tmp_path) in a for a in args[1:])  # шлях до файлу в аргументи не йде


def test_restore_failure_rolls_back_to_before_restore(tmp_path):
    runner = FakeRunner(restore_results=[1, 0])  # відновлення з копії падає, відкат успішний
    service, _ = make(tmp_path, runner)
    path = service.create_backup("manual")
    with pytest.raises(RestoreFailed) as caught:
        service.restore(path)
    assert caught.value.rolled_back
    assert "Нічого не змінено" in str(caught.value)
    assert service.events.count(("reset", "journal")) == 2  # друге скидання — це відкат
    assert len([c for c in runner.tools("pg_restore") if "--single-transaction" in c[0]]) == 2


def test_restore_failure_and_failed_rollback_points_to_safety_copy(tmp_path):
    runner = FakeRunner(restore_results=[1, 1])
    service, _ = make(tmp_path, runner)
    path = service.create_backup("manual")
    with pytest.raises(RestoreFailed) as caught:
        service.restore(path)
    assert not caught.value.rolled_back
    assert "before-restore" in str(caught.value)


def test_restore_aborts_when_safety_copy_fails(tmp_path):
    runner = FakeRunner()
    service, _ = make(tmp_path, runner)
    path = service.create_backup("manual")
    runner.dump_ok = False
    with pytest.raises(BackupError):
        service.restore(path)
    assert service.events == []  # відновлення навіть не починалось


def test_password_only_in_env_never_in_argv_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    runner = FakeRunner(restore_results=[1, 0])
    service, _ = make(tmp_path, runner)
    path = service.create_backup("manual")
    runner.dump_ok = False
    with pytest.raises(BackupError) as dump_error:
        service.create_backup("manual")
    runner.dump_ok = True
    with pytest.raises(RestoreFailed) as restore_error:
        service.restore(path)
    for args, env in runner.calls:
        assert PASSWORD not in " ".join(args)
        assert "-w" in args or "--list" in args or "--data-only" in args
        if Path(args[0]).stem == "pg_dump" or "--single-transaction" in args:
            assert env["PGPASSWORD"] == PASSWORD
    assert PASSWORD not in caplog.text
    assert PASSWORD not in str(dump_error.value) and PASSWORD not in str(restore_error.value)
    assert "***" in caplog.text  # зашифрований у журналі, а не втрачений


def test_default_dir_follows_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("JOURNAL_DATA_DIR", str(tmp_path / "дані"))
    assert bs.default_backup_dir() == tmp_path / "дані" / "backups"


# ---------------------------------------------------------------- маркер незавершеного відновлення

def test_marker_written_before_reset_and_removed_on_success(tmp_path):
    service, _ = make(tmp_path)
    path = service.create_backup("manual")
    seen = []
    service._reset_schema = lambda url: seen.append(service.marker_path.read_text(encoding="utf-8"))
    service.restore(path)
    assert len(seen) == 1 and seen[0].endswith("_before-restore.dump")
    assert not service.marker_path.exists()


def test_marker_removed_after_successful_rollback(tmp_path):
    service, _ = make(tmp_path, FakeRunner(restore_results=[1, 0]))
    path = service.create_backup("manual")
    with pytest.raises(RestoreFailed):
        service.restore(path)
    assert not service.marker_path.exists()


def test_marker_kept_when_rollback_fails(tmp_path):
    service, _ = make(tmp_path, FakeRunner(restore_results=[1, 1]))
    path = service.create_backup("manual")
    with pytest.raises(RestoreFailed):
        service.restore(path)
    assert service.interrupted_restore_copy() is not None


def test_no_marker_when_safety_copy_fails(tmp_path):
    runner = FakeRunner()
    service, _ = make(tmp_path, runner)
    path = service.create_backup("manual")
    runner.dump_ok = False
    with pytest.raises(BackupError):
        service.restore(path)
    assert not service.marker_path.exists()


def test_interrupted_restore_recovery(tmp_path):
    service, _ = make(tmp_path)
    safety = service.create_backup("before-restore")
    service.marker_path.write_text(str(safety), encoding="utf-8")
    assert service.interrupted_restore_copy() == safety
    service.recover_interrupted_restore(safety)
    assert service.events == ["dispose", ("reset", "journal"), "upgrade"]
    assert not service.marker_path.exists()
    assert safety.exists()  # нічого не видалено


def test_interrupted_restore_missing_file_clears_marker(tmp_path):
    service, _ = make(tmp_path)
    service.marker_path.write_text(str(tmp_path / "gone.dump"), encoding="utf-8")
    assert service.interrupted_restore_copy() is None
    assert not service.marker_path.exists()


def test_no_marker_means_nothing_to_recover(tmp_path):
    service, _ = make(tmp_path)
    assert service.interrupted_restore_copy() is None


def test_failed_recovery_keeps_marker(tmp_path):
    service, runner = make(tmp_path)
    safety = service.create_backup("before-restore")
    service.marker_path.write_text(str(safety), encoding="utf-8")
    runner.restore_results = [1]
    with pytest.raises(BackupError):
        service.recover_interrupted_restore(safety)
    assert service.marker_path.exists() and safety.exists()


# ---------------------------------------------------------------- тайм-аут, fallback

def test_auto_backup_uses_short_timeout_others_long(tmp_path):
    service, runner = make(tmp_path)
    service.create_backup("auto")
    service.create_backup("manual")
    dumps = [t for name, t in runner.timeouts if name == "pg_dump"]
    assert dumps == [bs.AUTO_TOOL_TIMEOUT_SEC, bs.TOOL_TIMEOUT_SEC] == [60, 600]


def test_backup_timeout_is_backup_error_without_leftovers(tmp_path):
    runner = FakeRunner()
    service, _ = make(tmp_path, runner)
    runner.raise_timeout = True
    with pytest.raises(BackupError, match="занадто довго"):
        service.create_backup("auto")
    assert not list((tmp_path / "default").glob("*"))


def test_fallback_used_resets_on_effective_dir(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    service, _ = make(tmp_path, backup_dir=blocker / "sub")
    service.effective_dir(create=True)
    assert service.fallback_used
    service.backup_dir = tmp_path / "ok"
    (tmp_path / "ok").mkdir()
    service.effective_dir()
    assert not service.fallback_used

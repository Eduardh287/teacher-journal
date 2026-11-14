"""Фейковий сервіс резервних копій для тестів інтерфейсу."""
from datetime import datetime
from pathlib import Path

from journal.services.backup_service import BackupInfo


class FakeBackupService:
    def __init__(self, backups=(), folder=Path("C:/копії"), error=None, restore_error=None, inspect_error=None):
        self.backups = list(backups)
        self.folder = folder
        self.error = error
        self.restore_error = restore_error
        self.inspect_error = inspect_error
        self.created: list[str] = []
        self.restored: list[Path] = []
        self.fallback_used = False

    def list_backups(self):
        return list(self.backups)

    def effective_dir(self, create=False):
        return self.folder

    def create_backup(self, kind="manual", **kw):
        if self.error:
            raise self.error
        self.created.append(kind)
        path = self.folder / f"journal_2026-11-14_10-00-00_{kind}.dump"
        self.backups.insert(0, BackupInfo(path, datetime(2026, 11, 14, 10, 0), kind))
        return path

    def inspect(self, path):
        if self.inspect_error:
            raise self.inspect_error
        return BackupInfo(Path(path), datetime(2026, 11, 1, 9, 30), "auto", "rev")

    def restore(self, path):
        if self.restore_error:
            raise self.restore_error
        self.restored.append(Path(path))
        return self.inspect(path)

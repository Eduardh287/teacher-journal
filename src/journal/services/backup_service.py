"""Резервні копії бази даних (етап 7a): pg_dump -Fc / pg_restore без жодного вікна Qt.

Безпека й надійність:
- пароль бази передається ЛИШЕ через змінну оточення PGPASSWORD дочірнього процесу;
  у командному рядку, журналі й текстах помилок його немає;
- шлях до файлу копії НІКОЛИ не передається в pg_dump/pg_restore (папка може бути з кирилицею
  чи на флешці): дамп іде в stdout, файл пише Python (спершу `.part`, потім атомарне перейменування);
  відновлення читає файл зі stdin;
- відновлення стирає схему public ЛИШЕ в базі з URL, який отримав сервіс. Перед цим завжди
  створюється копія «before-restore»; якщо відновлення не вдалося — вона автоматично повертається.
"""
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.engine import URL, make_url

from journal import embedded_db

log = logging.getLogger(__name__)

KINDS = ("auto", "manual", "before-restore", "before-migration")
KEEP_AUTO = 10
BACKUP_SUFFIX = ".dump"
_NAME_RE = re.compile(
    r"^journal_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_(auto|manual|before-restore|before-migration)\.dump$"
)
_TIME_FORMAT = "%Y-%m-%d_%H-%M-%S"
_COPY_HEADER = re.compile(r"^COPY\s+\S*alembic_version\b.*FROM stdin;\s*$", re.IGNORECASE)
TOOL_TIMEOUT_SEC = 600
AUTO_TOOL_TIMEOUT_SEC = 60  # копія при виході не має утримувати викладачку довго
RESTORE_MARKER_NAME = "restore-in-progress"

UNKNOWN_REVISION_TEXT = "Цю копію створено іншою або новішою версією програми — відновити її не можна."

KIND_TITLES = {
    "auto": "автоматична",
    "manual": "створена вручну",
    "before-restore": "перед відновленням",
    "before-migration": "перед оновленням бази",
}


class BackupError(RuntimeError):
    """Помилка резервного копіювання. Текст — зрозуміле повідомлення українською."""


class BackupTooNewError(BackupError):
    """Копію створено новішою версією програми."""


class RestoreFailed(BackupError):
    """Відновлення не вдалося. `rolled_back` — чи повернуто попередній стан автоматично."""

    def __init__(self, message: str, rolled_back: bool) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created: datetime
    kind: str  # один із KINDS або "unknown"
    revision: str | None = None

    @property
    def kind_title(self) -> str:
        return KIND_TITLES.get(self.kind, "невідомого типу")


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: str


Runner = Callable[..., RunResult]


def subprocess_runner(
    args: list[str],
    *,
    env: dict[str, str],
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    timeout: float = TOOL_TIMEOUT_SEC,
) -> RunResult:
    """Єдине місце, де запускаються pg_dump/pg_restore. Тести підміняють його фейком."""
    proc = subprocess.run(
        args,
        env=env,
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=embedded_db._CREATE_NO_WINDOW,
        timeout=timeout,
        check=False,
    )
    return RunResult(
        proc.returncode,
        proc.stdout if stdout is None else b"",
        (proc.stderr or b"").decode("utf-8", errors="replace"),
    )


def default_backup_dir() -> Path:
    """<корінь даних>\\backups (JOURNAL_DATA_DIR або %LOCALAPPDATA%\\teacher-journal)."""
    return embedded_db.requested_root() / "backups"


def backup_file_name(moment: datetime, kind: str) -> str:
    return f"journal_{moment.strftime(_TIME_FORMAT)}_{kind}{BACKUP_SUFFIX}"


def parse_backup_name(path: Path) -> tuple[datetime, str] | None:
    match = _NAME_RE.match(path.name)
    if not match:
        return None
    return datetime.strptime(match.group(1), _TIME_FORMAT), match.group(2)


def parse_revision(dump_sql: str) -> str | None:
    """Рядок COPY public.alembic_version ... із виводу pg_restore --data-only --table=alembic_version."""
    lines = dump_sql.splitlines()
    for index, line in enumerate(lines):
        if _COPY_HEADER.match(line):
            for row in lines[index + 1:]:
                if row.strip() == r"\.":
                    return None
                if row.strip():
                    return row.strip()
            return None
    return None


def known_revisions() -> set[str]:
    """Усі ревізії міграцій, які знає ця версія програми."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    res = embedded_db.resource_dir()
    cfg = Config(str(res / "alembic.ini"))
    cfg.set_main_option("script_location", str(res / "migrations"))
    return {s.revision for s in ScriptDirectory.from_config(cfg).walk_revisions()}


def _psycopg_dsn(url: URL) -> dict:
    return {
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "user": url.username,
        "password": url.password,
        "dbname": url.database,
        "autocommit": True,
        "connect_timeout": 10,
    }


def reset_public_schema(url: URL) -> None:
    """DROP SCHEMA public CASCADE; CREATE SCHEMA public; — у базі з вказаного URL і ніякій іншій."""
    import psycopg

    dsn = _psycopg_dsn(url)
    dsn["autocommit"] = False  # обидві команди — в одній транзакції
    with psycopg.connect(**dsn) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def database_has_data(url: URL) -> bool:
    """Чи є в базі таблиця alembic_version (тобто база не порожня)."""
    import psycopg

    with psycopg.connect(**_psycopg_dsn(url)) as conn:
        row = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()
    return bool(row and row[0])


class BackupService:
    def __init__(
        self,
        url: str | URL,
        *,
        pg_bin: Path,
        default_dir: Path,
        backup_dir: Path | None = None,
        runner: Runner = subprocess_runner,
        now: Callable[[], datetime] = datetime.now,
        dispose_engine: Callable[[], None] | None = None,
        reset_schema: Callable[[URL], None] = reset_public_schema,
        upgrade_schema: Callable[[str], None] = embedded_db.upgrade_schema,
        known_revs: Callable[[], set[str]] = known_revisions,
        marker_path: Path | None = None,
        has_data: Callable[[URL], bool] | None = None,
    ) -> None:
        self._url = make_url(url) if isinstance(url, str) else url
        self._pg_bin = Path(pg_bin)
        self.default_dir = Path(default_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self._run = runner
        self._now = now
        self._dispose = dispose_engine or (lambda: None)
        self._reset_schema = reset_schema
        self._upgrade_schema = upgrade_schema
        self._known_revs = known_revs
        # маркер «відновлення триває»: у ньому шлях до копії «перед відновленням»
        self.marker_path = Path(marker_path) if marker_path else embedded_db.requested_root() / RESTORE_MARKER_NAME
        self._has_data = has_data or database_has_data
        self.fallback_used = False  # остання копія пішла в типову папку, бо обрана недоступна

    @classmethod
    def for_app(cls, backup_dir: Path | str | None = None, **overrides) -> "BackupService":
        """Сервіс для поточної бази застосунку (engine з journal.db) і вбудованих/встановлених утиліт."""
        from journal import db

        engine = db.get_engine()
        root = embedded_db.pgsql_dir()
        pg_bin = (embedded_db.ascii_safe(root) or root) / "bin"
        params = dict(
            pg_bin=pg_bin,
            default_dir=default_backup_dir(),
            backup_dir=Path(backup_dir) if backup_dir else None,
            dispose_engine=engine.dispose,
        )
        params.update(overrides)
        return cls(engine.url, **params)

    # ------------------------------------------------------------ допоміжне

    def tools_available(self) -> bool:
        return (self._pg_bin / "pg_dump.exe").exists() and (self._pg_bin / "pg_restore.exe").exists()

    def _exe(self, name: str) -> str:
        exe = self._pg_bin / f"{name}.exe"
        if not exe.exists():
            exe = self._pg_bin / name
        return str(exe)

    def _conn_args(self) -> list[str]:
        args = ["-h", self._url.host or "localhost", "-p", str(self._url.port or 5432)]
        if self._url.username:
            args += ["-U", self._url.username]
        args += ["-w"]  # ніколи не питати пароль у консолі
        return args

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._url.password:
            env["PGPASSWORD"] = self._url.password
        return env

    def _scrub(self, text: str) -> str:
        password = self._url.password
        if password:
            text = text.replace(password, "***")
        return text[-2000:]

    def _tool(
        self, name: str, args: list[str], *, stdin=None, stdout=None, timeout: float = TOOL_TIMEOUT_SEC
    ) -> RunResult:
        try:
            result = self._run(
                [self._exe(name), *args], env=self._env(), stdin=stdin, stdout=stdout, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            log.error("%s не вклався в %s с — перервано", name, timeout)
            raise BackupError("Операція з резервною копією тривала занадто довго й була перервана.") from None
        except (OSError, subprocess.SubprocessError) as error:
            log.error("%s не запустився: %s", name, self._scrub(str(error)))
            raise BackupError(
                "Не вдалося запустити утиліту резервного копіювання. Деталі — у журналі."
            ) from None
        return result

    def _writable_dir(self, directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".write_test_{os.getpid()}"
            probe.write_bytes(b"")
            probe.unlink()
            return True
        except OSError:
            return False

    def effective_dir(self, *, create: bool = False) -> Path:
        """Папка для копій: обрана, якщо доступна; інакше типова."""
        self.fallback_used = False
        chosen = self.backup_dir
        if chosen is not None and chosen != self.default_dir:
            if (self._writable_dir(chosen) if create else chosen.is_dir()):
                return chosen
            self.fallback_used = True
        return self.default_dir

    # ------------------------------------------------------------ створення

    def create_backup(self, kind: str = "manual", *, default_folder_only: bool = False) -> Path:
        if kind not in KINDS:
            raise ValueError(f"Невідомий тип копії: {kind}")
        self.fallback_used = False
        if default_folder_only:
            target_dir = self.default_dir
        else:
            target_dir = self.effective_dir(create=True)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.error("Не вдалося створити папку копій", exc_info=True)
            raise BackupError("Не вдалося створити папку для резервних копій.") from None

        moment = self._now().replace(microsecond=0)
        while (target_dir / backup_file_name(moment, kind)).exists():
            moment += timedelta(seconds=1)  # дві копії в одну секунду не затирають одна одну
        final = target_dir / backup_file_name(moment, kind)
        part = final.with_name(final.name + ".part")

        try:
            with open(part, "wb") as handle:
                result = self._tool(
                    "pg_dump",
                    [*self._conn_args(), "-Fc", "--no-owner", "--no-privileges", "-d", self._url.database],
                    stdout=handle,
                    timeout=AUTO_TOOL_TIMEOUT_SEC if kind == "auto" else TOOL_TIMEOUT_SEC,
                )
            if result.returncode != 0 or part.stat().st_size == 0:
                log.error("pg_dump: код %s: %s", result.returncode, self._scrub(result.stderr))
                raise BackupError("Не вдалося створити резервну копію. Деталі — у журналі.")
            os.replace(part, final)
        except BackupError:
            part.unlink(missing_ok=True)
            raise
        except OSError:
            part.unlink(missing_ok=True)
            log.error("Не вдалося записати файл копії", exc_info=True)
            raise BackupError("Не вдалося записати файл резервної копії. Перевірте вільне місце.") from None
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        log.info("Резервна копія створена: тип=%s, файл=%s", kind, final.name)
        if kind == "auto":
            try:
                self.rotate(target_dir)
            except OSError:
                log.warning("Не вдалося видалити старі автокопії", exc_info=True)
        return final

    def rotate(self, directory: Path | None = None, keep: int = KEEP_AUTO) -> list[Path]:
        """Лишає `keep` найновіших автокопій; інші типи копій не чіпає."""
        directory = directory or self.effective_dir()
        autos = sorted(
            (p for p in directory.glob(f"*{BACKUP_SUFFIX}") if (parse_backup_name(p) or (0, ""))[1] == "auto"),
            key=lambda p: p.name,
            reverse=True,
        )
        removed = []
        for old in autos[keep:]:
            old.unlink(missing_ok=True)
            removed.append(old)
        return removed

    # ------------------------------------------------------------ перегляд

    def list_backups(self) -> list[BackupInfo]:
        """Копії в поточній папці, найновіші першими. Папку не створює."""
        directory = self.effective_dir()
        if not directory.is_dir():
            return []
        found = []
        for path in directory.glob(f"*{BACKUP_SUFFIX}"):
            parsed = parse_backup_name(path)
            if parsed is not None:
                found.append(BackupInfo(path, parsed[0], parsed[1]))
        return sorted(found, key=lambda b: (b.created, b.path.name), reverse=True)

    def inspect(self, path: Path) -> BackupInfo:
        """Перевіряє файл копії й читає її ревізію схеми. Кидає BackupError / BackupTooNewError."""
        path = Path(path)
        if not path.is_file():
            raise BackupError("Файл копії не знайдено.")
        parsed = parse_backup_name(path)
        if parsed is not None:
            created, kind = parsed
        else:
            created, kind = datetime.fromtimestamp(path.stat().st_mtime), "unknown"

        with open(path, "rb") as handle:
            listing = self._tool("pg_restore", ["--list"], stdin=handle)
        if listing.returncode != 0:
            log.error("pg_restore --list: код %s: %s", listing.returncode, self._scrub(listing.stderr))
            raise BackupError("Цей файл не схожий на резервну копію журналу або пошкоджений.")
        with open(path, "rb") as handle:
            data = self._tool(
                "pg_restore", ["--data-only", "--table=alembic_version", "-f", "-"], stdin=handle
            )
        if data.returncode != 0:
            log.error("pg_restore (ревізія): код %s: %s", data.returncode, self._scrub(data.stderr))
            raise BackupError("Не вдалося прочитати резервну копію. Деталі — у журналі.")
        revision = parse_revision(data.stdout.decode("utf-8", errors="replace"))
        if revision is None:
            raise BackupError("У файлі немає даних журналу (не знайдено версії бази).")
        if revision not in self._known_revs():
            raise BackupTooNewError(UNKNOWN_REVISION_TEXT)
        return BackupInfo(path, created, kind, revision)

    # ------------------------------------------------------------ відновлення

    def _load(self, path: Path) -> None:
        """Стирає public у БД цього сервісу й заливає копію зі stdin (одна транзакція)."""
        self._dispose()
        self._reset_schema(self._url)
        with open(path, "rb") as handle:
            result = self._tool(
                "pg_restore",
                [
                    *self._conn_args(),
                    "-d", self._url.database,
                    "--no-owner", "--no-privileges",
                    "--single-transaction", "--exit-on-error",
                ],
                stdin=handle,
            )
        if result.returncode != 0:
            log.error("pg_restore: код %s: %s", result.returncode, self._scrub(result.stderr))
            raise BackupError("pg_restore завершився з помилкою")
        self._upgrade_schema(self._url.render_as_string(hide_password=False))

    def _write_marker(self, safety: Path) -> None:
        try:
            self.marker_path.parent.mkdir(parents=True, exist_ok=True)
            self.marker_path.write_text(str(safety), encoding="utf-8")
        except OSError:
            log.error("Не вдалося записати маркер відновлення", exc_info=True)
            raise BackupError("Не вдалося почати відновлення. Деталі — у журналі.") from None

    def _clear_marker(self) -> None:
        try:
            self.marker_path.unlink(missing_ok=True)
        except OSError:
            log.warning("Не вдалося видалити маркер відновлення", exc_info=True)

    def restore(self, path: Path) -> BackupInfo:
        """Відновлює базу з копії. Повертає BackupInfo; при невдачі кидає RestoreFailed."""
        info = self.inspect(path)
        safety = self.create_backup("before-restore", default_folder_only=True)  # завжди в типову папку; не вдалося — відновлення не починається
        self._write_marker(safety)  # якщо процес обірветься — при наступному запуску запропонуємо повернення
        try:
            self._load(info.path)
        except Exception as error:  # noqa: BLE001
            log.error("Відновлення не вдалося (%s) — повертаю попередній стан", type(error).__name__)
            try:
                self._load(safety)
            except Exception:  # noqa: BLE001
                log.critical("Не вдалося повернути попередній стан; копія: %s", safety, exc_info=True)
                raise RestoreFailed(
                    "Відновлення не вдалося, і поточні дані теж не вдалося повернути автоматично. "
                    f"Не закривайте це повідомлення: копія ваших даних лежить тут: {safety}",
                    rolled_back=False,
                ) from None  # маркер лишається
            self._clear_marker()
            raise RestoreFailed(
                "Не вдалося відновити дані з копії. Нічого не змінено — працюйте як раніше.",
                rolled_back=True,
            ) from None
        self._clear_marker()
        log.info("Дані відновлено з копії %s", info.path.name)
        return info

    # ------------------------------------------------------------ незавершене відновлення

    def interrupted_restore_copy(self) -> Path | None:
        """Копія «перед відновленням» від обірваного відновлення або None.

        Якщо маркер є, а файл копії зник — пишемо в журнал і прибираємо маркер.
        """
        try:
            if not self.marker_path.is_file():
                return None
            target = Path(self.marker_path.read_text(encoding="utf-8").strip())
            parsed = parse_backup_name(target)
            if parsed is None or parsed[1] != "before-restore":
                log.error("Маркер відновлення вказує не на копію «перед відновленням»: %s", target.name)
            elif target.is_file():
                return target
            elif not target.parent.is_dir():
                # папка недоступна (напр. знято флешку) — маркер лишаємо, спробуємо наступного разу
                log.warning("Папка копії перед відновленням недоступна: %s", target.name)
                return None
            else:
                log.error("Маркер відновлення вказує на відсутній файл: %s", target.name)
        except (OSError, ValueError):
            log.error("Не вдалося прочитати маркер відновлення", exc_info=True)
        self._clear_marker()
        return None

    def recover_interrupted_restore(self, copy: Path) -> None:
        """Повертає дані з копії «перед відновленням». Нічого не видаляє, крім маркера після успіху."""
        try:
            has_data = self._has_data(self._url)
        except Exception:  # noqa: BLE001
            has_data = False
        if has_data:  # база не порожня: перед стиранням — страхова копія (за можливості)
            try:
                self.create_backup("before-restore", default_folder_only=True)
            except Exception:  # noqa: BLE001
                log.warning("Не вдалося зробити копію перед поверненням даних", exc_info=True)
        try:
            self._load(Path(copy))
        except Exception:  # noqa: BLE001
            log.critical("Не вдалося повернути дані з %s", Path(copy).name, exc_info=True)
            raise BackupError(
                f"Не вдалося повернути дані автоматично. Копія ваших даних лежить тут: {copy}"
            ) from None
        self._clear_marker()
        log.info("Дані повернуто з копії %s після обірваного відновлення", Path(copy).name)

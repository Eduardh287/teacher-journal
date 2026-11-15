"""Вбудований PostgreSQL для встановленої версії застосунку (без прав адміністратора).

Режим «bundled»: застосунок зібрано PyInstaller (sys.frozen) або задано JOURNAL_EMBEDDED=1,
і при цьому DATABASE_URL не задано. Тоді сервер PostgreSQL з каталогу {app}\\pgsql
запускається самим застосунком (initdb при першому запуску, далі pg_ctl start/stop).

Модуль не імпортує UI і моделі. Пароль бази ніколи не потрапляє в командний рядок і логи:
для initdb він іде через тимчасовий pwfile, для підключення — в URL у пам'яті процесу.
"""
import atexit
import hashlib
import logging
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR_NAME = "teacher-journal"
DB_NAME = "journal"
DB_USER = "journal"
PORT_FIRST = 54329
PORT_LAST = 54339
START_TIMEOUT_SEC = 60
DEFAULT_PGSQL_DIR = Path(r"C:\Program Files\PostgreSQL\17")
SECRET_LENGTH = 32

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EmbeddedDbError(RuntimeError):
    """Не вдалося підняти вбудовану базу даних. Текст — зрозуміле повідомлення українською."""


@dataclass(frozen=True)
class Layout:
    """Де лежать дані. Усі шляхи тут безпечні для PostgreSQL (лише ASCII)."""

    root: Path
    pgdata: Path
    logs: Path
    secret_file: Path
    port_file: Path
    branch: str  # "direct" | "short" | "fallback"


# ---------------------------------------------------------------- режим роботи

def is_bundled_mode() -> bool:
    """True, якщо треба запускати власний PostgreSQL (і DATABASE_URL не задано)."""
    if os.environ.get("DATABASE_URL"):
        return False
    return bool(getattr(sys, "frozen", False)) or os.environ.get("JOURNAL_EMBEDDED") == "1"


def pgsql_dir() -> Path:
    """Каталог з bin/lib/share PostgreSQL."""
    override = os.environ.get("JOURNAL_PGSQL_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "pgsql"
    return DEFAULT_PGSQL_DIR


def resource_dir() -> Path:
    """Де лежать alembic.ini та migrations/ (у PyInstaller — _internal)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- шляхи

def is_ascii(path: str | os.PathLike) -> bool:
    return str(path).isascii()


def to_short_path(path: str) -> str:
    """8.3-ім'я існуючого шляху (GetShortPathNameW). Якщо не вдалося — шлях без змін."""
    if sys.platform != "win32":
        return path
    try:
        import ctypes

        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        get_short.restype = ctypes.c_uint
        size = get_short(path, None, 0)
        if size == 0:
            return path
        buffer = ctypes.create_unicode_buffer(size)
        if get_short(path, buffer, size) == 0:
            return path
        return buffer.value
    except Exception:  # noqa: BLE001 — шлях просто лишиться як є
        log.warning("GetShortPathNameW не спрацював", exc_info=True)
        return path


def ascii_safe(path: Path, shorten=to_short_path) -> Path | None:
    """Шлях, який можна передати PostgreSQL: сам шлях, якщо він ASCII, інакше його 8.3-форма.

    Каталог мусить існувати. Якщо 8.3-імен немає (вимкнені на томі) — повертає None.
    """
    if is_ascii(path):
        return path
    short = Path(shorten(str(path)))
    return short if is_ascii(short) else None


def fallback_root(username: str | None = None, program_data: str | None = None) -> Path:
    """Запасний корінь даних у ProgramData: <sha1(ім'я користувача)[:12]> — лише ASCII."""
    if username is None:
        import getpass

        username = getpass.getuser()
    digest = hashlib.sha1(username.encode("utf-8")).hexdigest()[:12]
    base = program_data or os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base) / APP_DIR_NAME / digest


def requested_root() -> Path:
    """Бажаний корінь даних: JOURNAL_DATA_DIR або %LOCALAPPDATA%\\teacher-journal."""
    override = os.environ.get("JOURNAL_DATA_DIR")
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_DIR_NAME
    return Path.home() / ".teacher-journal"


def _restrict_to_current_user(path: Path) -> None:
    """У ProgramData каталог за замовчуванням читають інші — залишаємо доступ лише власнику.

    Fail closed: якщо обмежити доступ не вдалося, дані туди не кладемо.
    """
    import getpass

    icacls = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "icacls.exe"
    try:
        result = subprocess.run(
            [str(icacls), str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:(OI)(CI)F"],
            capture_output=True,
            creationflags=_CREATE_NO_WINDOW,
            timeout=30,
            check=False,
        )
        failed = result.returncode != 0
    except Exception:  # noqa: BLE001
        log.error("icacls не запустився", exc_info=True)
        failed = True
    if failed:
        log.error("Не вдалося обмежити доступ до запасної папки даних")
        raise EmbeddedDbError(
            "Не вдалося захистити запасну папку для даних журналу. "
            "Встановіть програму й дані в папку з латинською назвою (без кирилиці)."
        )


def resolve_layout(
    root: Path | None = None, shorten=to_short_path, fallback: Path | None = None
) -> Layout:
    """Обирає, де зберігати дані, і створює каталоги (гілки: direct / short / fallback)."""
    wanted = root if root is not None else requested_root()
    wanted.mkdir(parents=True, exist_ok=True)
    safe = ascii_safe(wanted, shorten)
    if safe is None:
        # Крок 3 зі специфікації: 8.3-імен немає — переходимо в ProgramData.
        branch = "fallback"
        safe = fallback if fallback is not None else fallback_root()
        safe.mkdir(parents=True, exist_ok=True)
        _restrict_to_current_user(safe)
    else:
        branch = "direct" if safe == wanted else "short"
    layout = Layout(
        root=safe,
        pgdata=safe / "pgdata",
        logs=safe / "logs",
        secret_file=safe / "db.secret",
        port_file=safe / "port",
        branch=branch,
    )
    layout.logs.mkdir(parents=True, exist_ok=True)
    log.info("Дані вбудованої БД: гілка шляху = %s", branch)
    return layout


# ---------------------------------------------------------------- секрет і порт

def generate_secret(length: int = SECRET_LENGTH) -> str:
    return secrets.token_hex((length + 1) // 2)[:length]


def secret_present(secret_file: Path) -> bool:
    """Файл db.secret існує й не порожній."""
    try:
        return bool(secret_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False


def load_or_create_secret(secret_file: Path) -> str:
    """Читає пароль бази з db.secret або створює новий. Значення нікуди не логується."""
    if secret_file.exists():
        value = secret_file.read_text(encoding="ascii").strip()
        if value:
            return value
    value = generate_secret()
    secret_file.write_text(value, encoding="ascii")
    return value


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(preferred: int | None, is_free=is_port_free) -> int:
    """Збережений порт (якщо вільний), інакше перший вільний у 54329–54339."""
    candidates = []
    if preferred is not None and PORT_FIRST <= preferred <= PORT_LAST:
        candidates.append(preferred)
    candidates.extend(p for p in range(PORT_FIRST, PORT_LAST + 1) if p not in candidates)
    for port in candidates:
        if is_free(port):
            return port
    raise EmbeddedDbError(
        f"Не знайдено вільного порту {PORT_FIRST}–{PORT_LAST} для бази даних. "
        "Закрийте зайві програми й спробуйте ще раз."
    )


def read_saved_port(port_file: Path) -> int | None:
    try:
        return int(port_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def build_url(password: str, port: int) -> str:
    # Пароль — лише літери й цифри, тому додаткове екранування не потрібне.
    return f"postgresql+psycopg://{DB_USER}:{password}@127.0.0.1:{port}/{DB_NAME}"


# ---------------------------------------------------------------- виклики PostgreSQL

def _run(cmd: list[str], timeout: int = 120, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        log.error("Команда PostgreSQL не завершилась за %s с: %s", timeout, Path(cmd[0]).name)
        raise EmbeddedDbError("База даних не відповіла вчасно. Деталі — у журналі.") from None


def _tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


class EmbeddedDb:
    """Один екземпляр керує одним сервером PostgreSQL з каталогу pgsql."""

    def __init__(self, layout: Layout, pg_root: Path | None = None) -> None:
        self.layout = layout
        root = pg_root if pg_root is not None else pgsql_dir()
        if not (root / "bin" / "pg_ctl.exe").exists():
            raise EmbeddedDbError(
                "Не знайдено файлів бази даних (pgsql). Перевстановіть застосунок."
            )
        safe = ascii_safe(root)
        if safe is None:
            raise EmbeddedDbError(
                "Застосунок встановлено в папку, шлях до якої PostgreSQL не підтримує. "
                "Встановіть його в папку з латинською назвою."
            )
        self.bin = safe / "bin"
        self.url: str | None = None
        self.port: int | None = None
        self.started_by_us = False  # сервер запустили ми — лише тоді вправі його зупиняти

    # -- допоміжне
    def _exe(self, name: str) -> str:
        return str(self.bin / f"{name}.exe")

    def _pg_ctl(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return _run([self._exe("pg_ctl"), *args, "-D", str(self.layout.pgdata)], timeout)

    def is_initialized(self) -> bool:
        return (self.layout.pgdata / "PG_VERSION").exists()

    def is_running(self) -> bool:
        return self._pg_ctl("status", timeout=30).returncode == 0

    def running_port(self) -> int | None:
        """Порт запущеного сервера: 4-й рядок postmaster.pid."""
        try:
            lines = (self.layout.pgdata / "postmaster.pid").read_text(encoding="ascii").splitlines()
            return int(lines[3])
        except (OSError, ValueError, IndexError):
            return read_saved_port(self.layout.port_file)

    # -- кроки
    def init_cluster(self, password: str) -> None:
        log.info("Перший запуск: initdb")
        fd, pwfile = tempfile.mkstemp(prefix="pw", dir=str(self.layout.root))
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(password)
            result = _run(
                [
                    self._exe("initdb"),
                    "-U", DB_USER,
                    "-E", "UTF8",
                    "--locale=C",
                    "--auth=scram-sha-256",
                    f"--pwfile={pwfile}",
                    "-D", str(self.layout.pgdata),
                ]
            )
        finally:
            try:
                os.unlink(pwfile)
            except OSError:
                log.warning("Не вдалося видалити тимчасовий pwfile")
        if result.returncode != 0:
            log.error("initdb завершився з кодом %s: %s", result.returncode, result.stderr[-2000:])
            raise EmbeddedDbError("Не вдалося створити базу даних (initdb). Деталі — у журналі.")

    def start(self) -> int:
        port = pick_port(read_saved_port(self.layout.port_file))
        self.layout.port_file.write_text(str(port), encoding="ascii")
        logfile = self.layout.logs / "postgres.log"
        log.info("Запуск PostgreSQL на порту %s", port)
        self.started_by_us = True  # навіть при збої: напівзапущений сервер теж зупиняємо самі
        try:
            # stdout/stderr у DEVNULL: сервер-нащадок успадковує дескриптори, і канал не закрився б.
            result = subprocess.run(
                [
                    self._exe("pg_ctl"), "start", "-w", "-t", str(START_TIMEOUT_SEC),
                    "-D", str(self.layout.pgdata),
                    "-l", str(logfile),
                    "-o", f"-p {port} -c listen_addresses=127.0.0.1",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
                timeout=START_TIMEOUT_SEC + 30,
                check=False,
            )
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            log.error("pg_ctl start не завершився вчасно")
            returncode = -1
        if returncode != 0 and self.is_running():
            # pg_ctl міг спізнитися з відповіддю, хоча сервер уже піднявся
            log.warning("pg_ctl start: код %s, але сервер працює", returncode)
            returncode = 0
        if returncode != 0:
            log.error("pg_ctl start: код %s; кінець postgres.log:\n%s", returncode, _tail(logfile))
            raise EmbeddedDbError("Не вдалося запустити базу даних. Деталі — у журналі.")
        return port

    def ensure_database(self, password: str, port: int) -> None:
        import psycopg

        try:
            with psycopg.connect(
                host="127.0.0.1", port=port, user=DB_USER, password=password,
                dbname="postgres", autocommit=True, connect_timeout=10,
            ) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
                ).fetchone()
                if not exists:
                    log.info("Створюю базу %s", DB_NAME)
                    conn.execute(f'CREATE DATABASE "{DB_NAME}" ENCODING \'UTF8\' TEMPLATE template0')
        except psycopg.Error as error:
            sqlstate = getattr(error, "sqlstate", None)  # лише код, без тексту (у ньому може бути пароль)
            log.error(
                "Не вдалося підключитися до вбудованої бази: %s%s",
                type(error).__name__,
                f" (sqlstate {sqlstate})" if sqlstate else "",
            )
            raise EmbeddedDbError(
                "Не вдалося підключитися до бази даних. Якщо це повторюється — перезавантажте "
                "комп'ютер. Деталі — у журналі."
            ) from None

    def ensure_running(self) -> str:
        """Піднімає сервер (за потреби — initdb) і повертає URL бази. Міграції — окремо."""
        if self.is_initialized() and not secret_present(self.layout.secret_file):
            raise EmbeddedDbError(
                "Знайдено дані бази, але немає файлу з паролем (db.secret). "
                "Відновіть файл із резервної копії."
            )
        password = load_or_create_secret(self.layout.secret_file)
        if not self.is_initialized():
            self.init_cluster(password)
        if self.is_running():
            port = self.running_port()
            if port is None:
                raise EmbeddedDbError("Сервер бази вже запущено, але порт невідомий.")
            log.info("Сервер уже працює (порт %s) — використовую його, зупиняти не буду", port)
        else:
            port = self.start()
        self.port = port
        self.ensure_database(password, port)
        self.url = build_url(password, port)
        return self.url

    def stop(self) -> None:
        """Зупиняє сервер лише якщо його запустили ми (чужий сервер не чіпаємо).

        pg_ctl stop завершується з кодом 1, коли сервера немає, тому спершу дивимось is_running().
        """
        if not self.started_by_us:
            return
        try:
            if self.is_running():
                result = self._pg_ctl("stop", "-m", "fast", "-w", "-t", "30", timeout=60)
                if result.returncode != 0:
                    log.warning("pg_ctl stop: код %s", result.returncode)
        finally:
            self.started_by_us = False
            self.url = None

    def force_stop(self) -> bool:
        """Зупиняє сервер незалежно від того, хто його запустив (для інсталятора).

        Якщо сервер не працює — нічого не робить і повертає True (pg_ctl stop у такому разі дав би код 1).
        Інакше True, коли після зупинки сервер справді не працює.
        """
        self.started_by_us = False
        self.url = None
        if not self.is_running():
            return True
        result = self._pg_ctl("stop", "-m", "fast", "-w", "-t", "30", timeout=60)
        if result.returncode != 0:
            log.warning("pg_ctl stop: код %s", result.returncode)
        return not self.is_running()


# ---------------------------------------------------------------- міграції

def upgrade_schema(url: str) -> None:
    """alembic upgrade head з alembic.ini та migrations/, що лежать у складі застосунку."""
    from alembic import command
    from alembic.config import Config

    res = resource_dir()
    cfg = Config(str(res / "alembic.ini"))
    cfg.set_main_option("script_location", str(res / "migrations"))
    cfg.attributes["database_url"] = url
    cfg.attributes["skip_logging_config"] = True
    log.info("Міграції: alembic upgrade head")
    try:
        command.upgrade(cfg, "head")
    except Exception as error:  # noqa: BLE001
        log.error("Міграція не вдалася: %s", type(error).__name__, exc_info=True)
        raise EmbeddedDbError(
            "Не вдалося оновити структуру бази даних. Деталі — у журналі. "
            "Якщо в базі вже були дані, їх копію перед оновленням збережено у папці резервних копій."
        ) from None


def script_head() -> str | None:
    """Остання ревізія міграцій, що лежать у складі застосунку."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    res = resource_dir()
    cfg = Config(str(res / "alembic.ini"))
    cfg.set_main_option("script_location", str(res / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def current_revision(url: str) -> str | None:
    """Поточна ревізія схеми з таблиці alembic_version."""
    import psycopg

    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def backup_before_migration(url: str) -> None:
    """Якщо схема стара — копія `before-migration` у типову папку; без копії міграції не буде.

    Нова (порожня) база копії не потребує. Помилка копії -> EmbeddedDbError.
    """
    import psycopg.errors

    try:
        revision = current_revision(url)
    except psycopg.errors.UndefinedTable:  # немає таблиці alembic_version: база ще не мігрована
        revision = None
    except Exception:  # noqa: BLE001 — не знаємо стану бази: міграцію не починаємо
        log.error("Не вдалося перевірити версію бази перед міграцією", exc_info=True)
        raise EmbeddedDbError(
            "Не вдалося перевірити версію бази даних перед оновленням, тому оновлення не виконано. "
            "Деталі — у журналі. Дані не змінено."
        ) from None
    if revision is None or revision == script_head():
        return
    from journal.services.backup_service import BackupError, BackupService

    root = pgsql_dir()
    service = BackupService(
        url,
        pg_bin=(ascii_safe(root) or root) / "bin",
        default_dir=requested_root() / "backups",
    )
    try:
        path = service.create_backup("before-migration", default_folder_only=True)
    except BackupError as error:
        log.error("Копія перед міграцією не створена: %s", error)
        raise EmbeddedDbError(
            "Не вдалося створити резервну копію перед оновленням бази, тому оновлення не виконано. "
            f"{error} Дані не змінено."
        ) from None
    log.info("Копія перед міграцією: %s", path.name)


# ---------------------------------------------------------------- публічний API

_instance: EmbeddedDb | None = None


def ensure_running() -> str:
    """Повертає URL вбудованої БД: запускає сервер і застосовує міграції (один раз за процес)."""
    global _instance
    if _instance is not None and _instance.url:
        return _instance.url
    layout = resolve_layout()
    db = EmbeddedDb(layout)
    try:
        url = db.ensure_running()
        backup_before_migration(url)
        upgrade_schema(url)
    except BaseException:
        try:
            db.stop()
        except Exception:  # noqa: BLE001
            log.warning("Не вдалося зупинити сервер після помилки", exc_info=True)
        raise
    if _instance is None:
        atexit.register(stop)
    _instance = db
    return url


def stop_server_for_installer() -> bool:
    """`--stop-server`: зупиняє сервер цієї установки (перед оновленням і видаленням). True — не працює."""
    layout = resolve_layout()
    if not (layout.pgdata / "PG_VERSION").exists():
        return True
    return EmbeddedDb(layout).force_stop()


def stop() -> None:
    """Зупиняє сервер, який запустили ми. Безпечно викликати повторно."""
    global _instance
    if _instance is None:
        return
    try:
        _instance.stop()
    except Exception:  # noqa: BLE001
        log.warning("Не вдалося зупинити вбудовану БД", exc_info=True)
    _instance = None

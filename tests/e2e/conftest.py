"""Фікстури наскрізних сценаріїв QA (docs/specs/qa-plan.md, агент B).

Реальні сторінки, діалоги й сервіси; база — лише journal_test. Кожен тест іде в одній
зовнішній транзакції з відкатом (фікстури `engine` і `session` з tests/conftest.py), а кожен
`session_scope` застосунку перенаправлено на SAVEPOINT цієї сесії: «commit» дії користувача
лише звільняє savepoint, «rollback» — відкочує до нього. Модальні вікна не блокують:
їх відкриває справжній exec(), а керує ними таймер (`drive`).
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # до будь-якого імпорту Qt
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import logging  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import date  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from journal import db, logging_setup  # noqa: E402
from journal.models import Teacher  # noqa: E402
from journal.services.auth_service import CurrentUser  # noqa: E402
from journal.ui import (  # noqa: E402, F401  (імпорт, щоб `session_scope` у них можна було підмінити)
    class_dialogs,
    classes_page,
    journal_dialogs,
    journal_grid,
    journals_page,
    main_window,
    rollover_dialog,
    settings_cards,
    theme,
)
from journal.ui.main_window import MainWindow  # noqa: E402

TODAY = date(2026, 11, 12)  # «сьогодні» для всіх сценаріїв: листопад, I семестр 2026-2027


class _FrozenDate:
    """Замінник `date` у модулях UI: `today()` заморожено, решта — звичайний date."""

    def __new__(cls, *args):
        return date(*args)

    @staticmethod
    def today() -> date:
        return TODAY


@pytest.fixture(scope="module", autouse=True)
def log_file(tmp_path_factory):
    """Файл журналу цього модуля: сценарій S10 читає його наприкінці."""
    root = logging.getLogger()
    level = root.level
    path = logging_setup.setup_logging(tmp_path_factory.mktemp("logs"))
    assert path is not None
    yield path
    logging_setup._remove_our_handlers(root)
    root.setLevel(level)


@pytest.fixture(autouse=True)
def _only_test_database(engine):
    name = db.get_engine().url.database or ""
    assert name.endswith("_test"), "e2e працюють лише з тестовою базою"


@pytest.fixture(autouse=True)
def _isolation(session, monkeypatch, qapp):
    """Транзакція з відкатом, заморожена дата, світла тема, коротке вікно ланцюжка 1→10/11/12."""

    @contextmanager
    def scope():
        with session.begin_nested():
            yield session

    monkeypatch.setattr(db, "session_scope", scope)
    for name, module in list(sys.modules.items()):
        if name.startswith("journal.") and name != "journal.db" and hasattr(module, "session_scope"):
            monkeypatch.setattr(module, "session_scope", scope)
    for module in (class_dialogs, journals_page, journal_dialogs):
        monkeypatch.setattr(module, "date", _FrozenDate)
    monkeypatch.setattr(journal_grid, "GRADE_CHAIN_MS", 80)
    monkeypatch.setattr(theme, "save_theme_name", lambda name: None)  # не писати в реєстр автора
    theme.apply_theme(qapp, "light")
    yield
    theme.apply_theme(qapp, "light")


@pytest.fixture(autouse=True)
def msgs(monkeypatch) -> list[tuple[str, str, str]]:
    """Статичні QMessageBox (warning/information/critical) не блокують, а записуються: (вид, заголовок, текст)."""
    seen: list[tuple[str, str, str]] = []

    def recorder(kind: str):
        def fake(parent=None, title="", text="", *args, **kwargs):
            seen.append((kind, title, text))
            return QMessageBox.StandardButton.Ok

        return staticmethod(fake)

    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, kind, recorder(kind))
    return seen


@pytest.fixture(autouse=True)
def _modal_watchdog(qapp):
    """Страховка: модальне вікно, яке висить понад ~2,5 с, закривається, а тест падає."""
    stuck: list[str] = []
    state = {"last": None}

    def tick():
        widget = QApplication.activeModalWidget()
        if widget is not None and state["last"] is widget:
            stuck.append(type(widget).__name__)
            widget.reject()
            state["last"] = None
        else:
            state["last"] = widget

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1200)
    yield
    timer.stop()
    assert not stuck, f"Модальне вікно, яке ніхто не закрив: {stuck}"


@pytest.fixture
def drive(qapp):
    """drive(action) — коли з'явиться модальне вікно, викликає action(вікно); якщо воно лишилося відкритим, закриває.

    Повертає об'єкт із полями seen / error / stayed_open і методом check().
    """
    runs: list = []

    def _drive(action, *, linger_ms: int = 400, timeout_s: float = 5.0):
        run = SimpleNamespace(seen=None, error=None, stayed_open=False, done=False, cancelled=False)
        deadline = time.monotonic() + timeout_s

        def check():
            assert run.error is None, f"Помилка в обробнику модального вікна: {run.error!r}"
            assert run.done, "Модальне вікно не з'явилося"

        run.check = check

        def close_if_open(widget):
            try:
                if widget.isVisible():
                    run.stayed_open = True
                    widget.reject()
            except RuntimeError:  # вікно вже знищено
                pass

        def poll():
            if run.cancelled:
                return
            widget = QApplication.activeModalWidget()
            if widget is None:
                if time.monotonic() > deadline:
                    run.error = TimeoutError("модальне вікно не з'явилося")
                else:
                    QTimer.singleShot(15, poll)
                return
            run.seen = widget
            try:
                action(widget)
            except BaseException as exc:  # noqa: BLE001 — показуємо в тесті через check()
                run.error = exc
            run.done = True
            QTimer.singleShot(linger_ms, lambda: close_if_open(widget))

        QTimer.singleShot(0, poll)
        runs.append(run)
        return run

    yield _drive
    for run in runs:
        run.cancelled = True


@pytest.fixture
def teacher(session) -> CurrentUser:
    row = Teacher(username="demo_teacher", password_hash="x", full_name="Демо Викладач")
    session.add(row)
    session.flush()
    return CurrentUser(row.id, row.username, row.full_name)


@pytest.fixture
def window(qtbot, teacher) -> MainWindow:
    """Справжнє головне вікно (offscreen, 1280×800)."""
    win = MainWindow(teacher)
    qtbot.addWidget(win)
    win.resize(1280, 800)
    win.show()
    qtbot.waitExposed(win)
    return win

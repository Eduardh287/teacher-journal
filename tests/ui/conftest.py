"""Фікстури тестів інтерфейсу: Qt без вікон (offscreen) і сторінка журналів на фейковому сервісі."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # до будь-якого імпорту Qt

from contextlib import nullcontext  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from journal.services.auth_service import CurrentUser  # noqa: E402
from journal.ui import journal_grid, journals_page, theme  # noqa: E402
from journal.ui.journals_page import JournalsPage  # noqa: E402
from tests.fakes.fake_journal_service import FakeJournalService  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_chain(monkeypatch, qapp):
    """Коротке вікно для ланцюжка 1→10/11/12 і світла тема."""
    monkeypatch.setattr(journal_grid, "GRADE_CHAIN_MS", 80)
    if theme.current_theme() != "light" or not qapp.styleSheet():  # тема вже світла — не перестилізовуємо все
        theme.apply_theme(qapp, "light")
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # справді знищити віджети тесту


@pytest.fixture
def fake() -> FakeJournalService:
    """Журнал 9-А: двоє активних учнів, один вибулий; два уроки в I семестрі (звичайний і КР)."""
    service = FakeJournalService(["Коваленко Олена", "Шевченко Іван"], archived_students=("Вибулий Петро",))
    service.add_lesson(date(2025, 9, 2), "regular")
    service.add_lesson(date(2025, 9, 9), "test", "Квадратні рівняння")
    return service


@pytest.fixture
def make_page(qtbot, monkeypatch):
    """Фабрика: відкриває сторінку журналів на заданому фейку (семестр за замовчуванням — I)."""

    def factory(service: FakeJournalService) -> JournalsPage:
        monkeypatch.setattr(journals_page, "semester_for_date", lambda d, boundaries=None: 1)
        page = JournalsPage(CurrentUser(1, "teacher", "Викладач"), api_factory=lambda: nullcontext(service))
        qtbot.addWidget(page)
        page.resize(1100, 700)
        page.show()
        page.open_journal(1)
        return page

    return factory


@pytest.fixture
def page(make_page, fake) -> JournalsPage:
    return make_page(fake)


def type_text(view, text: str) -> None:
    """Надсилає натискання клавіші з текстом (підходить для кирилиці й цифр)."""
    for event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(view, QKeyEvent(event_type, 0, Qt.KeyboardModifier.NoModifier, text))

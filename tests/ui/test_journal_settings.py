"""Налаштування журналу: межі семестрів (редагуються лише для архівного класу)."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import date

from journal.services.semesters import SemesterBoundaries
from journal.ui import journals_page
from journal.ui.journal_dialogs import JournalSettingsDialog
from tests.fakes.fake_journal_service import FakeJournalService


def make_fake(archived: bool) -> FakeJournalService:
    service = FakeJournalService(["Коваленко Олена"], class_archived=archived)
    service.add_lesson(date(2025, 9, 2))
    service.add_lesson(date(2026, 1, 15))
    return service


def open_dialog(qtbot, service):
    dialog = JournalSettingsDialog(1, lambda: nullcontext(service), service.journal)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def set_months(dialog, s1s, s1e, s2s, s2e):
    for key, month in (("s1_start", s1s), ("s1_end", s1e), ("s2_start", s2s), ("s2_end", s2e)):
        dialog.combos[key].setCurrentIndex(month - 1)


def test_active_journal_is_read_only(qtbot):
    dialog = open_dialog(qtbot, make_fake(False))
    assert not any(c.isEnabled() for c in dialog.combos.values())
    assert not dialog.save_button.isVisible()
    assert dialog.note_label.isVisible() and dialog.note_label.text() == "Змінюється в Налаштуваннях"


def test_archived_saves_new_boundaries(qtbot):
    service = make_fake(True)
    dialog = open_dialog(qtbot, service)
    assert all(c.isEnabled() for c in dialog.combos.values())
    set_months(dialog, 9, 11, 1, 6)
    dialog.save_button.click()
    assert dialog.result_info.boundaries == SemesterBoundaries(9, 11, 1, 6)
    assert service.journal.boundaries == SemesterBoundaries(9, 11, 1, 6)


def test_conflict_lists_lessons_and_reverts(qtbot):
    service = make_fake(True)
    dialog = open_dialog(qtbot, service)
    set_months(dialog, 9, 12, 2, 6)  # січень стає канікулами
    dialog.save_button.click()
    assert not dialog.error_label.isHidden()
    assert "9-А · Математика — 15.01.2026" in dialog.error_label.text()
    assert dialog.combos["s2_start"].currentData() == 1
    assert service.journal.boundaries == SemesterBoundaries(9, 12, 1, 6)
    assert dialog.result_info is None


def test_conflict_list_is_truncated(qtbot):
    service = make_fake(True)
    for day in range(1, 13):
        service.add_lesson(date(2026, 2, day))
    dialog = open_dialog(qtbot, service)
    set_months(dialog, 9, 12, 3, 6)  # 13 уроків (січень + лютий) у канікулах
    dialog.save_button.click()
    assert dialog.error_label.text().endswith("і ще 3")


def test_invalid_boundaries_show_error_without_service_call(qtbot):
    service = make_fake(True)
    dialog = open_dialog(qtbot, service)
    set_months(dialog, 9, 12, 12, 6)  # перетин
    dialog.save_button.click()
    assert not dialog.error_label.isHidden()
    assert service.calls_of("set_journal_semesters") == []


def test_menu_has_settings_and_delete_disabled_for_archived(make_page):
    page = make_page(make_fake(True))
    assert page.settings_action.text() == "Налаштування журналу"
    assert not page.delete_journal_action.isEnabled()
    assert page.menu_btn.isVisible()


def test_menu_delete_enabled_for_active(make_page):
    page = make_page(make_fake(False))
    assert page.delete_journal_action.isEnabled()


def test_open_journal_uses_journal_boundaries(make_page, monkeypatch):
    service = make_fake(False)
    service.journal = replace(service.journal, boundaries=SemesterBoundaries(9, 11, 1, 6))
    service.journals = [service.journal]
    page = make_page(service)
    seen = []
    monkeypatch.setattr(journals_page, "semester_for_date", lambda d, b=None: seen.append(b) or 2)
    page.open_journal(1)
    assert seen == [SemesterBoundaries(9, 11, 1, 6)]
    assert page._semester == 2

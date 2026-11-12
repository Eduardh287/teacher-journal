"""Картки налаштувань: семестри й предмети (на фейкових сервісах)."""
from datetime import date

from journal.services.journal_types import LessonConflict, SemesterConflict
from journal.services.semesters import SemesterBoundaries, SemesterError
from journal.ui.settings_cards import SemestersCard, SubjectsCard
from tests.fakes.fake_settings import FakeSettingsService, FakeSubjectService


def make_card(qtbot, service, on_saved=None):
    card = SemestersCard(1, service.factory(), on_saved=on_saved)
    qtbot.addWidget(card)
    card.show()
    return card


def conflict(n: int) -> LessonConflict:
    return LessonConflict(1, "9-А", "2026-2027", "Алгебра", date(2027, 1, n))


def test_load_shows_current_months(qtbot):
    card = make_card(qtbot, FakeSettingsService(SemesterBoundaries(9, 12, 2, 5)))
    assert [c.currentText() for c in (card.s1_start, card.s1_end, card.s2_start, card.s2_end)] == [
        "вересень", "грудень", "лютий", "травень"
    ]


def test_save_calls_service_and_reports(qtbot):
    service = FakeSettingsService(updated=3)
    refreshed = []
    card = make_card(qtbot, service, on_saved=lambda: refreshed.append(1))
    card.s1_end.setCurrentIndex(card.s1_end.findData(11))
    card.s2_end.setCurrentIndex(card.s2_end.findData(5))
    card.save_button.click()
    assert service.saved == [SemesterBoundaries(9, 11, 1, 5)]
    assert card.status.text() == "Збережено. Оновлено журналів: 3"
    assert not card.error.isVisible()
    assert refreshed == [1]


def test_semester_error_shown(qtbot):
    service = FakeSettingsService(error=SemesterError("Семестри не можуть перетинатися"))
    refreshed = []
    card = make_card(qtbot, service, on_saved=lambda: refreshed.append(1))
    card.save_button.click()
    assert card.error.isVisible()
    assert card.error.text() == "Семестри не можуть перетинатися"
    assert refreshed == []


def test_conflict_lists_capped_and_reverts(qtbot):
    conflicts = [conflict(n) for n in range(1, 15)]
    service = FakeSettingsService(error=SemesterConflict(conflicts))
    card = make_card(qtbot, service)
    card.s1_end.setCurrentIndex(card.s1_end.findData(10))
    card.s2_start.setCurrentIndex(card.s2_start.findData(3))
    card.save_button.click()
    text = card.error.text()
    assert "9-А · Алгебра — 01.01.2027" in text
    assert "10.01.2027" in text and "11.01.2027" not in text
    assert text.splitlines()[-1] == "і ще 4"
    assert card.boundaries() == SemesterBoundaries(9, 12, 1, 6)


def test_unexpected_error_generic(qtbot):
    card = make_card(qtbot, FakeSettingsService(error=RuntimeError("secret")))
    card.save_button.click()
    assert card.error.text() == "Не вдалося зберегти зміни"


def test_subjects_add_and_duplicate(qtbot):
    service = FakeSubjectService()
    changed = []
    card = SubjectsCard(service.factory(), on_changed=lambda: changed.append(1))
    qtbot.addWidget(card)
    card.show()
    assert card.subjects_label.text() == "Алгебра · Фізика"
    card.subject_edit.setText("Астрономія")
    card.subject_edit.returnPressed.emit()
    assert "Астрономія" in card.subjects_label.text()
    assert card.subject_edit.text() == "" and changed == [1]
    card.subject_edit.setText("Фізика")
    card.subject_edit.returnPressed.emit()
    assert card.subject_error.isVisible()
    assert card.subject_error.text() == "Предмет «Фізика» уже є"
    assert changed == [1]

"""Вікно переходу на новий навчальний рік: тексти, галочка, «Гаразд» / «Пізніше» (без БД)."""
from contextlib import contextmanager
from datetime import date

from PySide6.QtWidgets import QDialog, QMessageBox

from journal.services.rollover_service import RolloverItem
from journal.ui.rollover_dialog import RolloverDialog, item_text, maybe_run_rollover

TODAY = date(2027, 8, 15)
ACCEPT = QDialog.DialogCode.Accepted
REJECT = QDialog.DialogCode.Rejected


def promote(name="9-А", new="10-А", subjects=("Алгебра",), exists=False, count=28):
    return RolloverItem(1, name, "2026-2027", "promote", new, "2027-2028", exists, count, subjects)


def archive(name="11-Б"):
    return RolloverItem(2, name, "2026-2027", "archive", None, None, False, 20, ())


class FakeRollover:
    def __init__(self, items):
        self.items = items
        self.applied: list[tuple] = []
        self.fail = False

    def plan(self, teacher_id, today):
        return list(self.items)

    def apply(self, teacher_id, today, copy_journals=False):
        if self.fail:
            raise RuntimeError("boom")
        self.applied.append((teacher_id, today, copy_journals))
        return list(self.items)

    def factory(self):
        @contextmanager
        def make():
            yield self

        return make


class FakeWindow:
    def __init__(self):
        self.refreshed: list[str] = []
        outer = self

        class Page:
            def __init__(self, name):
                self.name = name

            def refresh(self):
                outer.refreshed.append(self.name)

        self.classes_page = Page("classes")
        self.journals_page = Page("journals")


def dialog_factory(result, copy=None, seen=None):
    def make(items, parent):
        dialog = RolloverDialog(items, parent)
        if seen is not None:
            seen.append(dialog)
        if copy is not None:
            dialog.copy_check.setChecked(copy)
        dialog.exec = lambda: result
        return dialog

    return make


def test_item_texts():
    assert item_text(promote()) == "9-А → 10-А (2027-2028), учнів: 28"
    assert item_text(promote("9-Б", "10-Б", exists=True)) == "9-Б → архів (10-Б уже існує)"
    assert item_text(archive()) == "11-Б → архів"


def test_dialog_lines_and_checkbox(qtbot):
    dialog = RolloverDialog([promote(), promote("9-Б", "10-Б", exists=True), archive()])
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.windowTitle() == "Навчальний рік завершено"
    assert [x.text() for x in dialog.lines] == [
        "9-А → 10-А (2027-2028), учнів: 28", "9-Б → архів (10-Б уже існує)", "11-Б → архів",
    ]
    assert dialog.copy_check.isVisible()
    assert dialog.copy_check.text() == "Створити такі самі журнали для нових класів"
    assert not dialog.copy_journals


def test_checkbox_hidden_without_subjects(qtbot):
    dialog = RolloverDialog([promote(subjects=()), archive()])
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.copy_check.isVisible()
    assert not dialog.copy_journals


def test_ok_applies_with_checkbox(qtbot):
    service = FakeRollover([promote(), archive()])
    window = FakeWindow()
    assert maybe_run_rollover(window, 7, TODAY, service.factory(), dialog_factory(ACCEPT, copy=True))
    assert service.applied == [(7, TODAY, True)]
    assert window.refreshed == ["classes", "journals"]


def test_ok_without_checkbox(qtbot):
    service = FakeRollover([promote()])
    maybe_run_rollover(FakeWindow(), 7, TODAY, service.factory(), dialog_factory(ACCEPT))
    assert service.applied == [(7, TODAY, False)]


def test_later_does_nothing(qtbot):
    service = FakeRollover([promote()])
    window = FakeWindow()
    assert not maybe_run_rollover(window, 7, TODAY, service.factory(), dialog_factory(REJECT, copy=True))
    assert service.applied == [] and window.refreshed == []


def test_empty_plan_shows_no_dialog(qtbot):
    seen: list = []
    service = FakeRollover([])
    assert not maybe_run_rollover(FakeWindow(), 7, TODAY, service.factory(), dialog_factory(ACCEPT, seen=seen))
    assert seen == [] and service.applied == []


def test_apply_error_shows_message_without_names(qtbot, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: shown.append(text))
    service = FakeRollover([promote()])
    service.fail = True
    window = FakeWindow()
    assert not maybe_run_rollover(window, 7, TODAY, service.factory(), dialog_factory(ACCEPT))
    assert len(shown) == 1 and "9-А" not in shown[0]
    assert window.refreshed == []

"""Вставка списку в поле «Додати учня»: відкриває імпорт, а не склеює рядки в одне ім'я."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # до будь-якого імпорту Qt

from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from journal.services.class_service import ImportResult, StudentInfo  # noqa: E402
from journal.ui import class_dialogs  # noqa: E402
from journal.ui.class_dialogs import ImportStudentsDialog, StudentDialog  # noqa: E402

LIST = "1. Іваненко Олена\n2. Шевченко Іван"


class StubImport:
    """Підміна ImportStudentsDialog: запам'ятовує текст і «закривається» із заданим результатом."""

    changed_on_exec = True
    seen: list[str] = []

    def __init__(self, teacher_id, class_id, initial_text="", parent=None):
        self.seen.append(initial_text)
        self.changed = False

    def exec(self):
        self.changed = self.changed_on_exec


@pytest.fixture
def stub(monkeypatch):
    StubImport.seen = []
    StubImport.changed_on_exec = True
    monkeypatch.setattr(class_dialogs, "ImportStudentsDialog", StubImport)
    return StubImport


def paste(dialog, text):
    QGuiApplication.clipboard().setText(text)
    dialog.name_edit.setFocus()
    QTest.keyClick(dialog.name_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)


def test_hint_shown_only_when_adding(qtbot):
    adding = StudentDialog(1, 1)
    qtbot.addWidget(adding)
    texts = [w.text() for w in adding.findChildren(type(adding.note_label))]
    assert "Можна вставити одразу весь список — кожен учень з нового рядка." in texts
    renaming = StudentDialog(1, 1, StudentInfo(5, "Коваленко Олена", 1, False))
    qtbot.addWidget(renaming)
    texts = [w.text() for w in renaming.findChildren(type(renaming.note_label))]
    assert not any("весь список" in t for t in texts)


def test_multiline_paste_accepted_closes_as_changed(qtbot, stub):
    dialog = StudentDialog(1, 1)
    qtbot.addWidget(dialog)
    paste(dialog, LIST)
    assert stub.seen == [LIST]
    assert dialog.changed
    assert dialog.result() == dialog.DialogCode.Accepted


def test_multiline_paste_cancelled_keeps_dialog_with_empty_field(qtbot, stub):
    stub.changed_on_exec = False
    dialog = StudentDialog(1, 1)
    qtbot.addWidget(dialog)
    paste(dialog, "\r\n".join(LIST.split("\n")))
    assert not dialog.changed
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog.name_edit.text() == ""


def test_single_line_and_blank_lines_paste_normally(qtbot, stub):
    dialog = StudentDialog(1, 1)
    qtbot.addWidget(dialog)
    paste(dialog, "Коваленко Олена")
    assert dialog.name_edit.text() == "Коваленко Олена"
    dialog.name_edit.clear()
    paste(dialog, "Коваленко Олена\n\n  \n")  # один непорожній рядок
    assert stub.seen == []


def test_context_menu_paste_action_opens_import(qtbot, stub):
    dialog = StudentDialog(1, 1)
    qtbot.addWidget(dialog)
    QGuiApplication.clipboard().setText(LIST)

    menu = dialog.name_edit.paste_menu()
    pastes = [a for a in menu.actions() if a.text() == "Вставити"]
    assert len(pastes) == 1
    pastes[0].trigger()
    assert stub.seen == [LIST]


def test_rename_mode_is_plain_line_edit(qtbot, stub):
    dialog = StudentDialog(1, 1, StudentInfo(5, "Коваленко Олена", 1, False))
    qtbot.addWidget(dialog)
    assert not hasattr(dialog.name_edit, "list_pasted")
    assert stub.seen == []


@pytest.fixture
def fake_service(monkeypatch):
    """Імпорт-діалог без БД: підміняємо service_scope на фейковий сервіс."""

    class FakeService:
        def preview_import(self, teacher_id, class_id, text):
            return ImportResult(added=len(text.splitlines()), skipped_duplicates=0)

    @contextmanager
    def fake_scope(service_cls):
        yield FakeService()

    monkeypatch.setattr(class_dialogs, "service_scope", fake_scope)


def test_import_dialog_prefilled_and_previews_immediately(qtbot, fake_service):
    dialog = ImportStudentsDialog(1, 1, LIST)
    qtbot.addWidget(dialog)
    assert dialog.text_edit.toPlainText() == LIST
    assert "Буде додано: 2" in dialog.preview_label.text()
    assert dialog.submit_button.isEnabled()


def test_html_only_table_paste_opens_import(qtbot, stub):
    dialog = StudentDialog(1, 1)
    qtbot.addWidget(dialog)
    mime = QMimeData()
    mime.setHtml("<table><tr><td>1</td><td>Іваненко Олена</td></tr><tr><td>2</td><td>Бойко Іван</td></tr></table>")
    QGuiApplication.clipboard().setMimeData(mime)
    dialog.name_edit.paste()
    assert stub.seen == ["1\tІваненко Олена\n2\tБойко Іван"]


def test_import_dialog_shows_hint_when_paste_gives_no_text(qtbot, fake_service):
    dialog = ImportStudentsDialog(1, 1)
    qtbot.addWidget(dialog)
    dialog.show()
    mime = QMimeData()
    mime.setHtml("<img src='x.png'>")
    dialog.text_edit.insertFromMimeData(mime)
    assert dialog.paste_hint.isVisible()

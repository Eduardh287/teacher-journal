"""Формати вставки списку учнів: Word/Excel (текст і HTML) та Windows-кінці рядків."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # до будь-якого імпорту Qt

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData  # noqa: E402

from journal.models import Teacher  # noqa: E402
from journal.services.class_service import ClassService  # noqa: E402
from journal.ui.class_dialogs import _ImportTextEdit, mime_to_text  # noqa: E402

TABLE = (
    "<html><head><style>td{color:red}</style></head><body><!--StartFragment-->"
    "<table><tr><td><p>1</p></td><td><p>Олена&nbsp;Іваненко</p></td></tr>"
    "<tr><td><p>2</p></td><td><p>Іван Шевченко</p></td></tr></table><!--EndFragment--></body></html>"
)


@pytest.fixture
def svc(session):
    teacher = Teacher(username="pytest_fmt", password_hash="x", full_name="Викладач")
    session.add(teacher)
    session.flush()
    service = ClassService(session)
    service.klass = service.create_class(teacher.id, "9-А", "2026-2027")
    service.tid = teacher.id
    return service


def names(svc):
    return [s.full_name for s in svc.list_students(svc.tid, svc.klass.id)]


def test_excel_columns_and_crlf(svc):
    text = "1\tІваненко\tОлена\tПетрівна\r\nІваненко\tАнна\r\n"
    assert svc.import_students(svc.tid, svc.klass.id, text).added == 2
    assert sorted(names(svc)) == ["Іваненко Анна", "Іваненко Олена Петрівна"]


def test_word_numbered_list(svc):
    assert svc.import_students(svc.tid, svc.klass.id, "1.\tШевченко Іван\r\n2.\tКоваленко Олена").added == 2


def html_only(html: str) -> QMimeData:
    mime = QMimeData()
    mime.setHtml(html)
    return mime


def test_html_table_becomes_tab_separated_lines():
    assert mime_to_text(html_only(TABLE)) == "1\tОлена Іваненко\n2\tІван Шевченко"


def test_html_paragraphs_and_breaks():
    html = "<p>Іваненко Олена</p><p>Шевченко Іван<br>Бойко Анна</p><ul><li>Мельник Ігор</li></ul>"
    assert mime_to_text(html_only(html)).split("\n") == [
        "Іваненко Олена", "Шевченко Іван", "Бойко Анна", "Мельник Ігор",
    ]


def test_plain_text_preferred_over_html():
    mime = html_only(TABLE)
    mime.setText("1\tПростий Текст")
    assert mime_to_text(mime) == "1\tПростий Текст"


def test_html_table_pastes_into_import_field_and_imports(qtbot, svc):
    edit = _ImportTextEdit()
    qtbot.addWidget(edit)
    assert edit.canInsertFromMimeData(html_only(TABLE))
    edit.insertFromMimeData(html_only(TABLE))
    assert edit.toPlainText() == "1\tОлена Іваненко\n2\tІван Шевченко"
    assert svc.import_students(svc.tid, svc.klass.id, edit.toPlainText()).added == 2


def test_nothing_textual_emits_paste_failed(qtbot):
    edit = _ImportTextEdit()
    qtbot.addWidget(edit)
    with qtbot.waitSignal(edit.paste_failed):
        edit.insertFromMimeData(html_only("<img src='x.png'>"))
    assert edit.toPlainText() == ""


def test_lines_without_letters_are_not_students():
    from journal.services.class_service import _parse_lines

    assert _parse_lines("1\nІваненко Олена\n—\n2.\nПетренко Іван") == [(2, "Іваненко Олена"), (5, "Петренко Іван")]

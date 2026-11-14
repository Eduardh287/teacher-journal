"""Експорт в Excel (UI): діалог періоду, кнопка в журналі, повідомлення про успіх і помилки. Без вікон і без запису в репозиторій."""
from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QFileDialog, QMessageBox

from journal.services import xlsx_writer
from journal.services.export_service import EMPTY_PERIOD_TEXT, PRESET_NAMES, ExportError
from journal.ui import export_dialog, theme
from journal.ui.export_dialog import CUSTOM_PERIOD, ExportDialog

TODAY = date(2026, 5, 20)


@pytest.fixture(params=["light", "dark"])
def themed(request, qapp):
    theme.apply_theme(qapp, request.param)
    return request.param


@pytest.fixture
def dialog(qtbot, fake, themed):
    widget = ExportDialog(fake.journal, today=TODAY)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_default_preset_is_current_semester(dialog):
    assert dialog.preset_combo.currentText() == "Поточний семестр"
    assert dialog.period() == (date(2026, 1, 1), date(2026, 6, 30))
    assert [dialog.preset_combo.itemText(i) for i in range(dialog.preset_combo.count())] == [*PRESET_NAMES, CUSTOM_PERIOD]
    assert not dialog.grab().isNull()


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("I семестр", (date(2025, 9, 1), date(2025, 12, 31))),
        ("II семестр", (date(2026, 1, 1), date(2026, 6, 30))),
        ("Весь рік", (date(2025, 9, 1), date(2026, 6, 30))),
        ("Цей місяць", (date(2026, 5, 1), date(2026, 5, 31))),
    ],
)
def test_presets_fill_dates(dialog, preset, expected):
    dialog.set_preset(preset)
    assert dialog.period() == expected
    assert dialog.preset_combo.currentText() == preset


def test_editing_a_date_switches_to_custom(dialog):
    dialog.set_preset("I семестр")
    dialog.from_edit.setDate(dialog.from_edit.date().addDays(10))
    assert dialog.preset_combo.currentText() == CUSTOM_PERIOD
    assert dialog.period()[0] == date(2025, 9, 11)


def test_reversed_range_is_rejected(dialog):
    dialog.to_edit.setDate(dialog.from_edit.date().addDays(-1))
    dialog.submit_button.click()
    assert dialog.error_label.isVisible() and dialog.result() == 0
    dialog.set_preset("Весь рік")
    dialog.submit_button.click()
    assert dialog.result() == 1


# ---------- кнопка й сценарій ----------


@pytest.fixture
def stubs(monkeypatch, tmp_path):
    """Підміна всіх вікон: нічого не показується, файл — лише в tmp_path."""
    calls = {"saved": [], "failure": [], "notice": []}
    state = {"period": (date(2025, 9, 1), date(2025, 12, 31)), "path": tmp_path / "out.xlsx"}
    monkeypatch.setattr(export_dialog, "ask_period", lambda parent, info: state["period"])
    monkeypatch.setattr(export_dialog, "choose_save_path", lambda parent, name: calls.setdefault("name", name) and state["path"])
    monkeypatch.setattr(export_dialog, "show_saved", lambda parent, path: calls["saved"].append(path))
    monkeypatch.setattr(export_dialog, "show_failure", lambda parent, text: calls["failure"].append(text))
    monkeypatch.setattr(export_dialog, "show_notice", lambda parent, text: calls["notice"].append(text))
    calls["state"] = state
    return calls


def test_button_exports_file(page, stubs, tmp_path):
    assert page.export_btn.text() == "Експорт в Excel…"
    page.export_btn.click()
    assert stubs["saved"] == [tmp_path / "out.xlsx"] and not stubs["failure"] and not stubs["notice"]
    assert stubs["name"] == "9-А_Математика_2025-09-01_2025-12-31.xlsx"
    ws = load_workbook(tmp_path / "out.xlsx")["Журнал"]
    assert ws["A1"].value == "Математика, 9-А — 01.09.2025–31.12.2025"
    assert ws["B5"].value == "Коваленко Олена"


def test_cancel_in_period_dialog_does_nothing(page, stubs, monkeypatch, tmp_path):
    monkeypatch.setattr(export_dialog, "ask_period", lambda parent, info: None)
    page.export_btn.click()
    assert not stubs["saved"] and not (tmp_path / "out.xlsx").exists()


def test_cancel_in_save_dialog_does_nothing(page, stubs, monkeypatch, tmp_path):
    monkeypatch.setattr(export_dialog, "choose_save_path", lambda parent, name: None)
    page.export_btn.click()
    assert not stubs["saved"] and not (tmp_path / "out.xlsx").exists()


def test_empty_period_shows_friendly_message(page, stubs, tmp_path):
    stubs["state"]["period"] = (date(2025, 11, 1), date(2025, 11, 30))
    page.export_btn.click()
    assert stubs["notice"] == [EMPTY_PERIOD_TEXT] and not stubs["saved"]
    assert not (tmp_path / "out.xlsx").exists()


def test_write_error_shows_message_and_no_file(page, stubs, monkeypatch, tmp_path):
    def locked(table, path):
        raise xlsx_writer.ExportWriteError(xlsx_writer.LOCKED_TEXT)

    monkeypatch.setattr(export_dialog, "write_export", locked)
    page.export_btn.click()
    assert stubs["failure"] == [xlsx_writer.LOCKED_TEXT] and not stubs["saved"]
    assert not (tmp_path / "out.xlsx").exists()


def test_unexpected_error_shows_generic_message(page, stubs, monkeypatch):
    monkeypatch.setattr(export_dialog, "build_export_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    page.export_btn.click()
    assert stubs["failure"] == [export_dialog.GENERIC_EXPORT_ERROR]


def test_service_error_is_shown_as_notice(page, stubs, monkeypatch):
    monkeypatch.setattr(export_dialog, "build_export_table", lambda *a, **k: (_ for _ in ()).throw(ExportError("Ой")))
    page.export_btn.click()
    assert stubs["notice"] == ["Ой"]


# ---------- вибір файлу й повідомлення ----------


def test_choose_save_path_remembers_folder_and_adds_extension(monkeypatch, tmp_path):
    seen = {}

    def fake_dialog(parent, caption, start, flt):
        seen["start"] = start
        return str(tmp_path / "звіт"), flt

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_dialog)
    path = export_dialog.choose_save_path(None, "a.xlsx")
    assert path == tmp_path / "звіт.xlsx"
    assert theme.app_settings().value(export_dialog.EXPORT_DIR_KEY) == str(tmp_path)
    export_dialog.choose_save_path(None, "b.xlsx")
    assert seen["start"] == str(tmp_path / "b.xlsx")  # наступного разу — запам'ятована папка


def test_choose_save_path_cancel(monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    assert export_dialog.choose_save_path(None, "a.xlsx") is None
    assert theme.app_settings().value(export_dialog.EXPORT_DIR_KEY) is None


def test_default_dir_falls_back_when_saved_folder_is_gone(tmp_path):
    theme.app_settings().setValue(export_dialog.EXPORT_DIR_KEY, str(tmp_path / "немає"))
    assert export_dialog.default_export_dir() != str(tmp_path / "немає")


def test_saved_box_has_open_folder_button(qtbot, tmp_path, themed):
    box, open_button = export_dialog.build_saved_box(None, tmp_path / "x.xlsx")
    qtbot.addWidget(box)
    assert box.text().startswith("Файл збережено") and "x.xlsx" in box.text()
    assert open_button.text() == "Відкрити папку"
    assert {b.text() for b in box.buttons()} == {"Відкрити папку", "Готово"}
    assert box.icon() == QMessageBox.Icon.Information

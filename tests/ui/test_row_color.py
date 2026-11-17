"""Колір рядка учня в журналі: малювання, пріоритет клітинок, меню, збереження через сервіс."""
from contextlib import contextmanager
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter

from journal.services.journal_types import CellInfo
from journal.ui import journal_grid, theme
from journal.ui.journal_grid import JournalCellDelegate, row_color_token

TOKEN = "row_blue"


def _paint_token(monkeypatch, page, row, col):
    """Який токен тла вибрав делегат для клітинки (перехоплюємо fillRect)."""
    model = page.grid_view.grid_model
    cell = model.cell(row, col)
    student = model.students[row]
    painted = []
    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    monkeypatch.setattr(theme, "color", lambda token: painted.append(token) or "#000000")
    JournalCellDelegate._fill(painter, img.rect(), cell, model.kind_at(col), student.archived, row_color_token(student))
    painter.end()
    return painted[0]


@pytest.fixture
def colored(page):
    model = page.grid_view.grid_model
    model.students[0] = replace(model.students[0], row_color="blue")
    model.students[2] = replace(model.students[2], row_color="blue")  # вибулий
    return page


def test_row_color_fills_lesson_cell(colored, monkeypatch):
    assert _paint_token(monkeypatch, colored, 0, 0) == TOKEN
    assert _paint_token(monkeypatch, colored, 1, 0) == "surface"


def test_cell_mark_wins_over_row_color(colored, monkeypatch):
    colored.grid_view.grid_model.cells[(1, 1)] = CellInfo("absent", None, None)
    assert _paint_token(monkeypatch, colored, 0, 0) == "mark_absent_soft"


def test_archived_student_stays_muted(colored, monkeypatch):
    assert row_color_token(colored.grid_view.grid_model.students[2]) is None
    assert _paint_token(monkeypatch, colored, 2, 0) == "hover"


def test_summary_columns_keep_own_tint(colored, monkeypatch):
    model = colored.grid_view.grid_model
    col = next(i for i in range(len(model.columns)) if model.kind_at(i) == "semester")
    assert _paint_token(monkeypatch, colored, 0, col) == theme.COLUMN_TINT["semester"]


@pytest.mark.parametrize("name", ["light", "dark"])
def test_all_row_color_tokens_exist_in_both_themes(qapp, name):
    theme.apply_theme(qapp, name)
    for _label, token in theme.ROW_COLORS.values():
        assert QColor(theme.color(token)).isValid()
    theme.apply_theme(qapp, "light")


def test_vertical_header_paints_with_color(colored):
    colored.grid_view.grab()  # не падає при малюванні заголовка з кольором


class _MenuProbe:
    """Підміна меню: замість показу — перевірка вмісту й вибір пункту."""

    def __init__(self, real_build, pick):
        self.real_build, self.pick, self.labels, self.shown = real_build, pick, None, False

    def __call__(self, *args, **kwargs):
        menu = self.real_build(*args, **kwargs)
        self.labels = [a.text() for a in menu.actions() if a.text()]
        probe = self

        class Stub:
            def exec(self, *_):
                probe.shown = True
                if probe.pick is not None:
                    menu.actions()[probe.pick].trigger()

        return Stub()


def test_student_menu_emits_chosen_color(page, monkeypatch):
    chosen = []
    page.grid_view.student_color_requested.connect(lambda sid, color: chosen.append((sid, color)))
    probe = _MenuProbe(journal_grid.build_color_menu, pick=2)  # «Блакитний»
    monkeypatch.setattr(journal_grid, "build_color_menu", probe)
    vheader = page.grid_view.verticalHeader()
    vheader.customContextMenuRequested.emit(QPoint(5, vheader.sectionViewportPosition(0) + 5))
    assert probe.labels == [name for name, _ in theme.ROW_COLORS.values()] + ["Без кольору"]
    assert chosen == [(1, "blue")]


def test_student_menu_ignores_archived(page, monkeypatch):
    probe = _MenuProbe(journal_grid.build_color_menu, pick=None)
    monkeypatch.setattr(journal_grid, "build_color_menu", probe)
    vheader = page.grid_view.verticalHeader()
    vheader.customContextMenuRequested.emit(QPoint(5, vheader.sectionViewportPosition(2) + 5))
    assert not probe.shown


def test_page_saves_color_via_class_service_and_reloads(page, fake, monkeypatch):
    saved = []

    class FakeClasses:
        def set_student_color(self, teacher_id, student_id, color):
            saved.append((student_id, color))

    @contextmanager
    def scope():
        yield FakeClasses()

    page._class_factory = scope
    page.grid_view.student_color_requested.emit(1, "pink")
    assert saved == [(1, "pink")]
    assert fake.calls_of("get_grid")


def test_class_page_table_really_paints_row_color(qtbot, qapp):
    """QSS ::item у темі змушує Qt ігнорувати BackgroundRole — делегат має намалювати колір сам."""
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

    from journal.ui import classes_page, theme

    theme.apply_theme(qapp, "light")
    table = QTableWidget(1, 1)
    qtbot.addWidget(table)
    table.setItemDelegate(classes_page._RowColorDelegate(table))
    item = QTableWidgetItem("Іваненко Олена")
    wanted = QColor(theme.color("row_green"))
    item.setBackground(QBrush(wanted))
    table.setItem(0, 0, item)
    table.resize(300, 120)
    table.show()
    qtbot.waitExposed(table)
    rect = table.visualItemRect(item)
    image = table.viewport().grab().toImage()
    assert image.pixelColor(rect.right() - 3, rect.center().y()) == wanted

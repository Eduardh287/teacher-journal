"""Виправлення за результатами QA: токени, QSS, WCAG-контраст, ElidedLabel, граматика."""
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication

from journal.services.grid_text import plural
from journal.ui import theme
from journal.ui.widgets import ElidedLabel


def _lum(hex_color: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hex_color[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_token_dicts_have_identical_keys():
    assert set(theme.TOKENS["light"]) == set(theme.TOKENS["dark"])
    assert {"control_border", "disabled"} <= set(theme.TOKENS["light"])


@pytest.mark.parametrize("name", theme.THEMES)
def test_stylesheet_substitutes_for_both_themes(name):
    sheet = theme.STYLESHEET.substitute(theme.TOKENS[name])
    assert "$" not in sheet
    assert theme.TOKENS[name]["control_border"] in sheet


@pytest.mark.parametrize("name", theme.THEMES)
def test_apply_theme_renders_images(qapp, name):
    theme.apply_theme(qapp, name)
    sheet = qapp.styleSheet()
    assert "$" not in sheet and "down-arrow" in sheet
    images = theme._render_images(name, theme.TOKENS[name])
    assert all(Path(p).is_file() and "\\" not in p for p in images.values())
    theme.apply_theme(qapp, "light")


TEXT_PAIRS = [
    ("text", "surface"), ("text", "bg"), ("muted", "surface"), ("muted", "bg"), ("muted", "hover"),
    ("muted", "input_bg"), ("muted", "accent_soft"), ("accent_text", "accent"), ("danger", "surface"),
    ("danger", "danger_soft"), ("mark_absent", "mark_absent_soft"), ("mark_sick", "mark_sick_soft"),
    ("mark_late", "mark_late_soft"),
]
CONTROL_PAIRS = [("control_border", bg) for bg in ("surface", "input_bg", "bg", "hover")]


@pytest.mark.parametrize("name", theme.THEMES)
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_contrast(name, fg, bg):
    t = theme.TOKENS[name]
    assert ratio(t[fg], t[bg]) >= 4.5, (name, fg, bg, ratio(t[fg], t[bg]))


@pytest.mark.parametrize("name", theme.THEMES)
@pytest.mark.parametrize("fg,bg", CONTROL_PAIRS)
def test_control_border_contrast(name, fg, bg):
    t = theme.TOKENS[name]
    assert ratio(t[fg], t[bg]) >= 3.0, (name, fg, bg, ratio(t[fg], t[bg]))


@pytest.mark.parametrize(
    "n,expected",
    [(1, "учня"), (2, "учні"), (4, "учні"), (5, "учнів"), (11, "учнів"), (12, "учнів"),
     (21, "учня"), (22, "учні"), (34, "учні"), (100, "учнів")],
)
def test_students_word(n, expected):
    assert plural(n, "учня", "учні", "учнів") == expected


def _tooltip(widget):
    QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), widget.mapToGlobal(QPoint(5, 5))))


def test_elided_label_minimum_width_and_tooltip(qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr("journal.ui.widgets.QToolTip.showText", lambda pos, text, w=None: shown.append(text))
    long = ElidedLabel("Дуже довга назва класу і предмета " * 3)
    qtbot.addWidget(long)
    long.resize(120, 30)
    long.show()
    assert long.minimumSizeHint().width() == 0
    assert long.is_elided()
    _tooltip(long)
    assert shown == [long.text()]

    short = ElidedLabel("9-А")
    qtbot.addWidget(short)
    short.resize(200, 30)
    short.show()
    shown.clear()
    assert not short.is_elided()
    _tooltip(short)
    assert shown == []

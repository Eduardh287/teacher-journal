"""Світла та темна теми застосунку.

Усі кольори задані «токенами» в TOKENS. Таблиця стилів (QSS) — це шаблон,
у який підставляються токени активної теми. Щоб змінити колір у всьому
застосунку, достатньо поправити одне значення тут.
"""
from string import Template

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("light", "dark")
DEFAULT_THEME = "light"

TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F6F7FB",          # тло вікна
        "surface": "#FFFFFF",     # картки, бічна панель
        "hover": "#F2F4F7",       # наведення
        "border": "#E4E7EC",
        "text": "#101828",
        "muted": "#667085",       # другорядний текст
        "input_bg": "#FFFFFF",
        "accent": "#4F46E5",      # індиго
        "accent_hover": "#4338CA",
        "accent_soft": "#EEF2FF",
        "accent_text": "#FFFFFF",
        "danger": "#D92D20",
        "danger_soft": "#FEF3F2",
        # Позначки в таблиці журналу (етап 5)
        "mark_absent": "#D92D20",
        "mark_absent_soft": "#FEE4E2",
        "mark_sick": "#B54708",
        "mark_sick_soft": "#FEF0C7",
        "mark_late": "#175CD3",
        "mark_late_soft": "#D1E9FF",
        "lesson_test_soft": "#F4EBFF",
        "lesson_lab_soft": "#DCFAE6",
        "lesson_independent_soft": "#FEF6EE",
    },
    "dark": {
        "bg": "#0F1117",
        "surface": "#171A23",
        "hover": "#1F2330",
        "border": "#2A2F3C",
        "text": "#E6E8EE",
        "muted": "#9AA1B2",
        "input_bg": "#1D212C",
        "accent": "#818CF8",
        "accent_hover": "#A5B4FC",
        "accent_soft": "#252A4A",
        "accent_text": "#0F1117",
        "danger": "#F97066",
        "danger_soft": "#2A1715",
        "mark_absent": "#F97066",
        "mark_absent_soft": "#3A1A18",
        "mark_sick": "#FDB022",
        "mark_sick_soft": "#3A2A10",
        "mark_late": "#84CAFF",
        "mark_late_soft": "#132A45",
        "lesson_test_soft": "#2E2350",
        "lesson_lab_soft": "#123222",
        "lesson_independent_soft": "#3A2814",
    },
}

STYLESHEET = Template(
    r"""
QWidget { font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: $text; }
QMainWindow, QDialog, QWidget#Content { background: $bg; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 4px 8px; }

/* Бічна панель */
QFrame#Sidebar { background: $surface; border-right: 1px solid $border; }
QLabel#Brand { font-size: 12pt; font-weight: 600; }
QLabel#BrandMark { background: $accent; border-radius: 10px; }
QListWidget#Nav { background: transparent; border: none; outline: 0; }
QListWidget#Nav::item { padding: 9px 10px; margin: 2px 0; border-radius: 8px; color: $muted; }
QListWidget#Nav::item:hover { background: $hover; color: $text; }
QListWidget#Nav::item:selected { background: $accent_soft; color: $accent; font-weight: 600; }
QFrame#Divider { background: $border; border: none; }
QLabel#Avatar { background: $accent_soft; color: $accent; border-radius: 18px; font-weight: 600; }

/* Заголовки та текст */
QLabel#AppTitle { font-size: 16pt; font-weight: 600; }
QLabel#PageTitle { font-size: 18pt; font-weight: 600; }
QLabel#CardTitle { font-size: 11pt; font-weight: 600; }
QLabel#EmptyTitle { font-size: 12pt; font-weight: 600; }
QLabel[muted="true"] { color: $muted; }
QLabel[fieldLabel="true"] { color: $muted; font-size: 9pt; font-weight: 600; }
QLabel[error="true"] { color: $danger; background: $danger_soft; border-radius: 8px; padding: 8px 10px; }

/* Картки */
QFrame#Card { background: $surface; border: 1px solid $border; border-radius: 12px; }

/* Картка класу: така сама, як Card, але з підсвіткою рамки при наведенні */
QFrame#ClassCard { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame#ClassCard:hover { border: 1px solid $accent; }
QLabel#CardBig { font-size: 16pt; font-weight: 600; background: transparent; }
QLabel#Badge { background: $accent_soft; color: $accent; border-radius: 6px; padding: 2px 8px; font-size: 9pt; font-weight: 600; }

/* Поля вводу */
QLineEdit, QComboBox, QPlainTextEdit {
    background: $input_bg; border: 1px solid $border; border-radius: 8px;
    padding: 8px 10px; selection-background-color: $accent; selection-color: $accent_text;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid $accent; }

/* Прапорець */
QCheckBox { spacing: 8px; }

/* Таблиця учнів */
QTableWidget, QTableView {
    background: $surface; border: 1px solid $border; border-radius: 12px;
    gridline-color: $border; outline: 0; selection-background-color: $accent_soft; selection-color: $text;
}
QTableWidget::item, QTableView::item { padding: 6px 10px; border-bottom: 1px solid $border; }
QTableWidget::item:selected, QTableView::item:selected { background: $accent_soft; color: $text; }
QHeaderView { background: transparent; }
QTableView QTableCornerButton::section { background: $surface; border: none; }

/* Календар (спливає з поля дати). Його внутрішня таблиця — теж QTableView, тому
   скасовуємо для неї загальні стилі таблиць: рамки, відступи й лінії ламали сітку днів. */
QCalendarWidget QTableView {
    background: $surface; border: none; border-radius: 0; gridline-color: transparent;
    selection-background-color: $accent; selection-color: $accent_text; outline: 0;
}
QCalendarWidget QTableView::item { padding: 0; border: none; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: $accent; }
QCalendarWidget QToolButton {
    color: $accent_text; background: transparent; border: none; padding: 4px 8px; font-weight: 600;
}
QCalendarWidget QToolButton:hover { background: $accent_hover; border-radius: 6px; }
QCalendarWidget QSpinBox { background: $surface; color: $text; border: none; padding: 2px 6px; }
QHeaderView::section {
    background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 8px 10px; font-weight: 600; font-size: 9pt;
}

/* Прозора область прокрутки */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* Кнопки */
QPushButton {
    background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px 16px;
}
QPushButton:hover { background: $hover; }
QPushButton[variant="primary"] { background: $accent; color: $accent_text; border: none; font-weight: 600; }
QPushButton[variant="primary"]:hover { background: $accent_hover; }
QPushButton[variant="primary"]:disabled { background: $border; color: $muted; }
QPushButton[variant="ghost"] { background: transparent; border: none; color: $muted; text-align: left; padding: 8px 10px; }
QPushButton[variant="ghost"]:hover { background: $hover; color: $text; }
QPushButton[segment="true"] { padding: 8px 18px; }
QPushButton[segment="true"]:checked { background: $accent_soft; color: $accent; border: 1px solid $accent; font-weight: 600; }

/* Смуги прокрутки */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""
)

_current_theme = DEFAULT_THEME


def _settings() -> QSettings:
    return QSettings("TeacherJournal", "TeacherJournal")


def load_theme_name() -> str:
    """Читає збережену тему; якщо значення некоректне — повертає світлу."""
    name = _settings().value("theme", DEFAULT_THEME)
    return name if name in THEMES else DEFAULT_THEME


def save_theme_name(name: str) -> None:
    """Запам'ятовує обрану тему між запусками."""
    _settings().setValue("theme", name)


def current_theme() -> str:
    return _current_theme


def color(token: str) -> str:
    """Колір токена в активній темі (для іконок, які не стилізуються через QSS)."""
    return TOKENS[_current_theme][token]


def _palette(t: dict[str, str]) -> QPalette:
    """Палітра Qt для елементів, які малює сам стиль Fusion (меню, діалоги, курсори)."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["input_bg"],
        QPalette.ColorRole.AlternateBase: t["surface"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.Highlight: t["accent"],
        QPalette.ColorRole.HighlightedText: t["accent_text"],
        QPalette.ColorRole.PlaceholderText: t["muted"],
        QPalette.ColorRole.ToolTipBase: t["surface"],
        QPalette.ColorRole.ToolTipText: t["text"],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    return p


def apply_theme(app: QApplication, name: str) -> None:
    """Застосовує тему "light" або "dark" до всього застосунку."""
    global _current_theme
    if name not in THEMES:
        raise ValueError(f"Невідома тема: {name}")
    _current_theme = name
    tokens = TOKENS[name]
    app.setStyle("Fusion")
    QGuiApplication.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if name == "dark" else Qt.ColorScheme.Light
    )
    app.setPalette(_palette(tokens))
    app.setStyleSheet(STYLESHEET.substitute(tokens))

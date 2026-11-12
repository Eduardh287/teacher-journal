"""Сторінка «Журнали»: список журналів (картки) і вигляд журналу з таблицею оцінок.

UI працює лише з JournalApi (через api_factory) та його DTO. За замовчуванням кожен виклик —
окрема транзакція journal.db.session_scope(). JournalError ловимо ПОЗА блоком with (відкат).
"""
from dataclasses import replace
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from journal.db import session_scope
from journal.services.auth_service import CurrentUser
from journal.services.journal_types import (
    AttendanceCode,
    CellInfo,
    GridData,
    JournalApi,
    JournalError,
    JournalInfo,
    LessonInfo,
    semester_for_date,
)
from journal.ui import icons, theme
from journal.ui.journal_dialogs import DeleteLessonDialog, LessonDialog, NewJournalDialog
from journal.ui.journal_grid import JournalGridView
from journal.ui.widgets import button, card, label

COLUMNS = 3  # кількість карток у рядку
BANNER_MS = 5000  # скільки видно повідомлення про помилку
GENERIC_ERROR_TEXT = "Не вдалося виконати дію. Спробуйте ще раз."

ApiFactory = Callable[[], AbstractContextManager[JournalApi]]


@contextmanager
def default_api_factory() -> Iterator[JournalApi]:
    """Відкриває транзакцію й віддає сервіс журналів (імпорт відкладений — сервіс пишеться окремо)."""
    from journal.services.journal_service import JournalService

    with session_scope() as session:
        yield JournalService(session)


def lessons_text(n: int) -> str:
    """«1 урок», «2 уроки», «5 уроків», «11 уроків»."""
    if n % 100 in (11, 12, 13, 14):
        word = "уроків"
    elif n % 10 == 1:
        word = "урок"
    elif n % 10 in (2, 3, 4):
        word = "уроки"
    else:
        word = "уроків"
    return f"{n} {word}"


class _JournalCard(QFrame):
    """Клікабельна картка журналу."""

    clicked = Signal()

    def __init__(self, info: JournalInfo) -> None:
        super().__init__()
        self.setObjectName("ClassCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(f"{info.class_name} · {info.subject_name}", object_name="CardBig"))
        top.addStretch(1)
        if info.class_archived:
            top.addWidget(label("Архів", object_name="Badge"), alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addWidget(label(info.school_year, muted=True))
        layout.addStretch(1)
        layout.addWidget(label(lessons_text(info.lesson_count)))
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class JournalsPage(QWidget):
    def __init__(
        self,
        current_user: CurrentUser,
        api_factory: ApiFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.teacher_id = current_user.id
        self._api_factory: ApiFactory = api_factory or default_api_factory
        self._journal_id: int | None = None
        self._semester = 1
        self._grid: GridData | None = None
        self._icon_refreshers: list[Callable[[], None]] = []

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list_view())     # 0
        self.stack.addWidget(self._build_journal_view())  # 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.show_list()
        self.refresh_icons()

    # ------------------------------------------------------------------
    # Звернення до сервісу
    # ------------------------------------------------------------------

    def _call(self, action: Callable[[JournalApi], Any], *, banner: bool = False) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат); помилку показує."""
        try:
            with self._api_factory() as api:
                result = action(api)
        except JournalError as error:
            self._report(str(error), banner)
            return False, None
        except Exception:
            logging.exception("Помилка під час роботи з журналами")
            self._report(GENERIC_ERROR_TEXT, banner)
            return False, None
        return True, result

    def _report(self, text: str, banner: bool) -> None:
        if banner and self.stack.currentIndex() == 1:
            self.show_banner(text)
        else:
            QMessageBox.warning(self, "Не вдалося виконати дію", text)

    def show_banner(self, text: str) -> None:
        self.banner.setText(text)
        self.banner.show()
        self._banner_timer.start(BANNER_MS)

    def _confirm(self, text: str, accept_text: str) -> bool:
        """Підтвердження дії; кнопка за замовчуванням — «Скасувати»."""
        box = QMessageBox(QMessageBox.Icon.Question, "Підтвердження", text, parent=self)
        accept = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is accept

    # ------------------------------------------------------------------
    # Список журналів
    # ------------------------------------------------------------------

    def _build_list_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label("Журнали", object_name="PageTitle"))
        layout.addWidget(label("Журнал — це клас і предмет. Оберіть, щоб відкрити таблицю оцінок.", muted=True))
        layout.addSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        header.addStretch(1)
        self.archived_check = QCheckBox("Показати архівні")
        self.archived_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.archived_check.toggled.connect(lambda _: self.show_list())
        header.addWidget(self.archived_check)
        self.new_journal_btn = button("Новий журнал", variant="primary")
        self.new_journal_btn.clicked.connect(self._on_new_journal)
        self._icon_refreshers.append(
            lambda: self.new_journal_btn.setIcon(icons.icon("plus", theme.color("accent_text"), size=16))
        )
        header.addWidget(self.new_journal_btn)
        layout.addLayout(header)
        layout.addSpacing(8)

        self.list_stack = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.list_stack.addWidget(self.scroll)                    # 0 — картки
        self.list_stack.addWidget(self._build_empty_journals())   # 1 — порожньо
        layout.addWidget(self.list_stack, 1)
        return view

    def _build_empty_journals(self) -> QWidget:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        frame, layout = card()
        layout.setContentsMargins(40, 48, 40, 48)
        heading = label("Ще немає жодного журналу", object_name="EmptyTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        hint = label("Створіть журнал для свого класу й предмета.", muted=True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        action = button("Новий журнал", variant="primary")
        action.clicked.connect(self._on_new_journal)
        layout.addWidget(action, alignment=Qt.AlignmentFlag.AlignHCenter)
        holder_layout.addWidget(frame)
        holder_layout.addStretch(1)
        return holder

    def show_list(self) -> None:
        """Перемикає на список і заново будує картки."""
        self.grid_view.flush_pending()
        self._journal_id = None
        ok, journals = self._call(lambda api: api.list_journals(self.teacher_id, self.archived_check.isChecked()))
        journals = journals if ok else []
        if not journals:
            self.list_stack.setCurrentIndex(1)
        else:
            host = QWidget()
            grid = QGridLayout(host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(16)
            for column in range(COLUMNS):
                grid.setColumnStretch(column, 1)
            for index, info in enumerate(journals):
                journal_card = _JournalCard(info)
                journal_card.clicked.connect(lambda i=info: self.open_journal(i.id))
                grid.addWidget(journal_card, index // COLUMNS, index % COLUMNS)
            grid.setRowStretch(len(journals) // COLUMNS + 1, 1)
            self.scroll.setWidget(host)
            self.list_stack.setCurrentIndex(0)
        self.stack.setCurrentIndex(0)

    def _on_new_journal(self) -> None:
        dialog = NewJournalDialog(self.teacher_id, self._api_factory, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_info is not None:
            self.open_journal(dialog.result_info.id)

    # ------------------------------------------------------------------
    # Вигляд журналу
    # ------------------------------------------------------------------

    def _build_journal_view(self) -> QWidget:
        view = QWidget()
        self.journal_view = view
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        back = button("← Журнали", variant="ghost")
        back.clicked.connect(self.show_list)
        back_row = QHBoxLayout()
        back_row.addWidget(back)
        back_row.addStretch(1)
        layout.addLayout(back_row)

        self.title_label = label("", object_name="PageTitle")
        self.subtitle_label = label("", muted=True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(12)

        # Панель: перемикач семестрів, «Новий урок», меню
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.semester_buttons: dict[int, Any] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for number, text in ((1, "I семестр"), (2, "II семестр")):
            seg = button(text)
            seg.setProperty("segment", True)
            seg.setCheckable(True)
            group.addButton(seg, number)
            bar.addWidget(seg)
            self.semester_buttons[number] = seg
        group.idClicked.connect(self._on_semester_clicked)
        bar.addStretch(1)
        self.new_lesson_btn = button("Новий урок", variant="primary")
        self.new_lesson_btn.clicked.connect(self._on_new_lesson)
        self._icon_refreshers.append(
            lambda: self.new_lesson_btn.setIcon(icons.icon("plus", theme.color("accent_text"), size=16))
        )
        bar.addWidget(self.new_lesson_btn)
        self.menu_btn = button("Ще")
        menu = QMenu(self.menu_btn)
        self.delete_journal_action = menu.addAction("Видалити журнал")
        self.delete_journal_action.triggered.connect(self._on_delete_journal)
        self.menu_btn.setMenu(menu)
        bar.addWidget(self.menu_btn)
        layout.addLayout(bar)

        # Рядок помилки (ховається за 5 с)
        self.banner = QLabel()
        self.banner.setProperty("error", True)
        self.banner.setWordWrap(True)
        self.banner.hide()
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self.banner.hide)
        layout.addWidget(self.banner)
        layout.addSpacing(4)

        # Таблиця або порожній стан
        self.content_stack = QStackedWidget()
        self.grid_view = JournalGridView()
        self.grid_view.saver = self._save_cell
        self.grid_view.lesson_edit_requested.connect(self._on_edit_lesson)
        self.grid_view.lesson_delete_requested.connect(self._on_delete_lesson)
        self.content_stack.addWidget(self.grid_view)            # 0
        self.content_stack.addWidget(self._build_empty_grid())  # 1
        layout.addWidget(self.content_stack, 1)

        shortcut = QShortcut(QKeySequence("Ctrl+N"), view)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.new_lesson_today)
        self.new_lesson_shortcut = shortcut
        return view

    def _build_empty_grid(self) -> QWidget:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        frame, layout = card()
        layout.setContentsMargins(40, 40, 40, 40)
        self.empty_label = label("", object_name="EmptyTitle")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self.empty_lesson_btn = button("Новий урок", variant="primary")
        self.empty_lesson_btn.clicked.connect(self._on_new_lesson)
        layout.addWidget(self.empty_lesson_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        holder_layout.addWidget(frame)
        holder_layout.addStretch(1)
        return holder

    def open_journal(self, journal_id: int) -> None:
        """Відкриває журнал на семестрі за сьогоднішньою датою (канікули — 1 семестр)."""
        try:
            semester = semester_for_date(date.today())
        except JournalError:
            semester = 1
        self._journal_id = journal_id
        self._semester = semester
        self.banner.hide()
        if self.reload_grid():
            self.stack.setCurrentIndex(1)
            self.grid_view.select_cell(0, 0)
            self.grid_view.setFocus()
        else:
            self.show_list()

    def refresh(self) -> None:
        """Оновлює сторінку при поверненні на неї (класи чи учні могли змінитися)."""
        if self.stack.currentIndex() == 1:
            self.reload_grid()
        else:
            self.show_list()

    def reload_grid(self, select_lesson_id: int | None = None) -> bool:
        """Підтягує таблицю семестру. Повертає False, якщо журнал недоступний."""
        self.grid_view.flush_pending()
        journal_id, semester = self._journal_id, self._semester
        ok, grid = self._call(lambda api: api.get_grid(self.teacher_id, journal_id, semester), banner=True)
        if not ok:
            return False
        self._grid = grid
        self.grid_view.set_grid(grid)
        info = grid.journal
        self.title_label.setText(f"{info.class_name} · {info.subject_name}")
        self.subtitle_label.setText(info.school_year + (" · клас в архіві, лише перегляд" if info.class_archived else ""))
        self.semester_buttons[grid.semester].setChecked(True)
        for widget in (self.new_lesson_btn, self.menu_btn):
            widget.setVisible(not info.class_archived)
        self.new_lesson_shortcut.setEnabled(not info.class_archived)

        if not grid.students:
            self.empty_label.setText("У класі немає учнів")
            self.empty_lesson_btn.hide()
        elif not grid.lessons:
            self.empty_label.setText("Уроків у цьому семестрі ще немає")
            self.empty_lesson_btn.setVisible(not info.class_archived)
        self.content_stack.setCurrentIndex(0 if grid.students and grid.lessons else 1)
        if select_lesson_id is not None:
            column = self.grid_view.grid_model.column_of(select_lesson_id)
            self.grid_view.select_cell(0, column)
        return True

    def _on_semester_clicked(self, semester: int) -> None:
        if semester == self._semester:
            return
        self.grid_view.flush_pending()
        previous, self._semester = self._semester, semester
        if self.reload_grid():
            self.grid_view.select_cell(0, 0)
        else:
            self._semester = previous
            self.semester_buttons[previous].setChecked(True)

    def _save_cell(
        self, student_id: int, lesson_id: int, attendance: AttendanceCode, grade: int | None, comment: str | None
    ) -> tuple[bool, CellInfo | None]:
        return self._call(
            lambda api: api.set_cell(self.teacher_id, lesson_id, student_id, attendance, grade, comment),
            banner=True,
        )

    # --- уроки ---

    def _lesson(self, lesson_id: int) -> LessonInfo | None:
        return next((x for x in self.grid_view.grid_model.lessons if x.id == lesson_id), None)

    def _on_new_lesson(self) -> None:
        dialog = LessonDialog(self.teacher_id, self._api_factory, self._journal_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_info is not None:
            self._show_lesson(dialog.result_info)

    def new_lesson_today(self) -> None:
        """Ctrl+N: звичайний урок на сьогодні без діалогу."""
        if self._grid is None or self._grid.journal.class_archived:
            return
        journal_id = self._journal_id
        ok, lesson = self._call(
            lambda api: api.create_lesson(self.teacher_id, journal_id, date.today(), "regular", None), banner=True
        )
        if ok:
            self._show_lesson(lesson)

    def _show_lesson(self, lesson: LessonInfo) -> None:
        """Переходить на семестр уроку й виділяє його першу клітинку."""
        self._semester = lesson.semester
        self.reload_grid(select_lesson_id=lesson.id)
        self.grid_view.setFocus()

    def _on_edit_lesson(self, lesson_id: int) -> None:
        lesson = self._lesson(lesson_id)
        if lesson is None:
            return
        dialog = LessonDialog(self.teacher_id, self._api_factory, self._journal_id, lesson, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_info is not None:
            self._show_lesson(dialog.result_info)

    def _on_delete_lesson(self, lesson_id: int) -> None:
        lesson = self._lesson(lesson_id)
        if lesson is None:
            return
        # Кількість позначок рахуємо за поточною таблицею, а не за даними останнього
        # завантаження: оцінки, щойно введені з клавіатури, теж мають захищати урок.
        live_count = sum(1 for (_, lid) in self.grid_view.grid_model.cells if lid == lesson_id)
        lesson = replace(lesson, entry_count=max(lesson.entry_count, live_count))
        if lesson.entry_count == 0:
            if not self._confirm(f"Видалити урок {lesson.lesson_date:%d.%m.%Y}?", "Видалити"):
                return
        elif DeleteLessonDialog(lesson, parent=self).exec() != QDialog.DialogCode.Accepted:
            return
        ok, _ = self._call(lambda api: api.delete_lesson(self.teacher_id, lesson_id), banner=True)
        if ok:
            self.reload_grid()

    def _on_delete_journal(self) -> None:
        if self._grid is None:
            return
        info = self._grid.journal
        text = f"Видалити журнал «{info.class_name} · {info.subject_name}»? Цю дію не можна скасувати."
        if not self._confirm(text, "Видалити"):
            return
        journal_id = info.id
        ok, _ = self._call(lambda api: api.delete_journal(self.teacher_id, journal_id), banner=True)
        if ok:
            self.show_list()

    # ------------------------------------------------------------------
    # Тема
    # ------------------------------------------------------------------

    def refresh_icons(self) -> None:
        """Перемальовує іконки та таблицю після зміни теми."""
        for refresh in self._icon_refreshers:
            refresh()
        self.grid_view.viewport().update()
        self.grid_view.horizontalHeader().viewport().update()
        self.grid_view.verticalHeader().viewport().update()

"""Сторінка «Класи»: список класів (картки) і детальний вигляд класу зі списком учнів.

UI працює лише з ClassService (через ui.service_scope) та його DTO.
Кожен виклик сервісу — окрема транзакція; ClassError ловимо ПОЗА блоком with,
щоб транзакція відкотилась, і показуємо його користувачу.
"""
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from journal.services.auth_service import CurrentUser
from journal.services.class_service import ClassError, ClassInfo, ClassService, StudentInfo
from journal.services.grid_text import plural
from journal.services.journal_types import SemesterConflict
from journal.ui import icons, theme
from journal.ui.class_dialogs import ClassDialog, ImportStudentsDialog, StudentDialog
from journal.ui.service_scope import service_scope
from journal.ui.widgets import CardListView, EntityCard, button, confirm, conflict_text, empty_state, label

GENERIC_ERROR_TEXT = "Не вдалося виконати дію. Спробуйте ще раз."


def _students_text(n: int) -> str:
    return f"{n} {plural(n, 'учень', 'учні', 'учнів')}"


class _ClassCard(EntityCard):
    """Клікабельна картка класу."""

    def __init__(self, info: ClassInfo) -> None:
        super().__init__(info.name, info.school_year, _students_text(info.student_count), info.archived)


class ClassesPage(QWidget):
    def __init__(self, current_user: CurrentUser, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.teacher_id = current_user.id
        self._current_class: ClassInfo | None = None  # клас, відкритий у детальному вигляді
        self._students: list[StudentInfo] = []
        self._removal_mode = "delete"
        # Іконки малюються кольором теми — зберігаємо, як їх оновити при зміні теми.
        self._icon_refreshers: list[Callable[[], None]] = []

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list_view())    # індекс 0
        self.stack.addWidget(self._build_detail_view())  # індекс 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.show_list()
        self.refresh_icons()

    # ------------------------------------------------------------------
    # Звернення до сервісу
    # ------------------------------------------------------------------

    def _call(self, action: Callable[[ClassService], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат); помилку показує."""
        try:
            with service_scope(ClassService) as service:
                result = action(service)
        except ClassError as error:
            QMessageBox.warning(self, "Не вдалося виконати дію", str(error))
            return False, None
        except SemesterConflict as error:  # повернення класу з архіву (рецензія Fable, PR #11)
            QMessageBox.warning(
                self,
                "Клас не повернуто з архіву",
                conflict_text(error.conflicts)
                + "\n\nПісля повернення клас отримує загальні межі семестрів. "
                "Змініть їх у «Налаштування» → «Семестри» або перенесіть чи видаліть ці уроки "
                "в журналі (журнал архівного класу можна редагувати), а тоді поверніть клас ще раз.",
            )
            return False, None
        except Exception:
            logging.exception("Помилка під час роботи з класами")
            QMessageBox.warning(self, "Помилка", GENERIC_ERROR_TEXT)
            return False, None
        return True, result

    def _confirm(self, text: str, accept_text: str) -> bool:
        return confirm(self, text, accept_text)

    # ------------------------------------------------------------------
    # Список класів
    # ------------------------------------------------------------------

    def _build_list_view(self) -> QWidget:
        empty = empty_state(
            "Ще немає жодного класу",
            "Створіть клас і додайте до нього список учнів.",
            ("Новий клас", self._on_new_class),
            icon="users",
            action_icon="plus",
            vertical_padding=48,
        )
        view = CardListView(
            "Класи", "Списки учнів, для яких ви ведете журнали.", "Новий клас", self._on_new_class, self.show_list, empty
        )
        self.list_view = view
        self.archived_check, self.list_stack, self.scroll = view.archived_check, view.list_stack, view.scroll
        self._icon_refreshers.append(empty.refresh_icons)
        self._icon_refreshers.append(
            lambda: view.new_button.setIcon(icons.icon("plus", theme.color("accent_text"), size=16))
        )
        return view

    def refresh(self) -> None:
        """Оновлює сторінку ззовні (напр., після переходу на новий навчальний рік)."""
        self.show_list()

    def show_list(self) -> None:
        """Перемикає на список і заново будує картки (порядок — як віддає сервіс)."""
        self._current_class = None
        include_archived = self.archived_check.isChecked()
        ok, classes = self._call(lambda s: s.list_classes(self.teacher_id, include_archived))
        if not ok:
            classes = []
        cards = [_ClassCard(info) for info in classes]
        for class_card, info in zip(cards, classes):
            class_card.clicked.connect(lambda i=info: self.open_class(i.id))
        self.list_view.show_cards(cards)
        self.stack.setCurrentIndex(0)

    def _on_new_class(self) -> None:
        dialog = ClassDialog(self.teacher_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.show_list()

    # ------------------------------------------------------------------
    # Детальний вигляд класу
    # ------------------------------------------------------------------

    def _build_detail_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        back = button("← Класи", variant="ghost")
        back.clicked.connect(self.show_list)
        back_row = QHBoxLayout()
        back_row.addWidget(back)
        back_row.addStretch(1)
        layout.addLayout(back_row)

        self.detail_title = label("", object_name="PageTitle")
        self.detail_subtitle = label("", muted=True)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_subtitle)
        layout.addSpacing(16)

        # Кнопки дій над класом. Для архівного класу видно лише «Повернути з архіву».
        self.add_student_btn = button("Додати учня", icon_name="plus")
        self.add_student_btn.clicked.connect(self._on_add_student)
        self._icon_refreshers.append(
            lambda: self.add_student_btn.setIcon(icons.icon("plus", theme.color("muted"), size=16))
        )
        self.import_btn = button("Додати списком", variant="primary")
        self.import_btn.clicked.connect(self._on_import)
        self.edit_class_btn = button("Редагувати клас")
        self.edit_class_btn.clicked.connect(self._on_edit_class)
        self.remove_class_btn = button("Видалити клас")
        self.remove_class_btn.clicked.connect(self._on_remove_class)
        self.restore_class_btn = button("Повернути з архіву")
        self.restore_class_btn.clicked.connect(self._on_restore_class)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for widget in (
            self.add_student_btn,
            self.import_btn,
            self.edit_class_btn,
            self.remove_class_btn,
            self.restore_class_btn,
        ):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addSpacing(12)

        # Таблиця учнів або «порожній стан»
        self.students_stack = QStackedWidget()
        self.students_stack.addWidget(self._build_students_table())  # 0
        self.students_stack.addWidget(self._build_empty_students())  # 1
        layout.addWidget(self.students_stack, 1)
        return view

    def _build_students_table(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        table = QTableWidget(0, 2)
        self.table = table
        table.setHorizontalHeaderLabels(["№", "Прізвище та ім'я"])
        table.horizontalHeaderItem(1).setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(38)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 80)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setHighlightSections(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_table_menu)
        table.itemSelectionChanged.connect(self._update_student_buttons)
        table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(table, 1)

        # Кнопки під таблицею діють на виділений рядок
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_student_btn = button("Змінити")
        self.edit_student_btn.clicked.connect(self._on_edit_student)
        self.remove_student_btn = button("Прибрати")
        self.remove_student_btn.clicked.connect(self._on_remove_student)
        row.addWidget(self.edit_student_btn)
        row.addWidget(self.remove_student_btn)
        row.addStretch(1)
        self.student_buttons = QWidget()
        self.student_buttons.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.student_buttons)
        return holder

    def _build_empty_students(self) -> QWidget:
        empty = empty_state("У класі ще немає учнів", action=("Додати списком", self._on_import))
        self.empty_import_btn = empty.action
        return empty

    def open_class(self, class_id: int) -> None:
        """Відкриває детальний вигляд класу."""
        self._load_detail(class_id)

    def _load_detail(self, class_id: int) -> None:
        """Підтягує клас і його учнів з бази та перемальовує детальний вигляд."""

        def load(service: ClassService):
            info = next(
                (c for c in service.list_classes(self.teacher_id, include_archived=True)
                 if c.id == class_id),
                None,
            )
            if info is None:
                raise ClassError("Клас не знайдено")
            students = service.list_students(self.teacher_id, class_id)
            mode = "delete" if info.archived else service.class_removal_mode(self.teacher_id, class_id)
            return info, students, mode

        ok, data = self._call(load)
        if not ok:
            self.show_list()  # клас зник або недоступний — повертаємось до списку
            return
        self._current_class, self._students, self._removal_mode = data
        self._render_detail()
        self.stack.setCurrentIndex(1)

    def _reload_detail(self) -> None:
        if self._current_class is not None:
            self._load_detail(self._current_class.id)

    def _render_detail(self) -> None:
        info = self._current_class
        self.detail_title.setText(f"{info.name} · {info.school_year}")
        subtitle = _students_text(len([s for s in self._students if not s.archived]))
        self.detail_subtitle.setText(subtitle + (" · клас в архіві" if info.archived else ""))

        archived = info.archived
        for widget in (self.add_student_btn, self.import_btn, self.edit_class_btn, self.remove_class_btn):
            widget.setVisible(not archived)
        self.restore_class_btn.setVisible(archived)
        self.remove_class_btn.setText("Архівувати" if self._removal_mode == "archive" else "Видалити клас")

        self._fill_table()
        self.students_stack.setCurrentIndex(0 if self._students else 1)
        self.empty_import_btn.setVisible(not archived)
        self.student_buttons.setVisible(not archived)
        self._update_student_buttons()

    def _fill_table(self) -> None:
        """Заповнює таблицю: активні за номерами, вибулі внизу приглушеним кольором."""
        muted = QBrush(QColor(theme.color("muted")))
        self.table.setRowCount(len(self._students))
        for row, student in enumerate(self._students):
            number = QTableWidgetItem("вибув" if student.archived else str(student.position))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(student.full_name)
            name.setToolTip(student.full_name)
            for item in (number, name):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if student.archived:
                    item.setForeground(muted)
            self.table.setItem(row, 0, number)
            self.table.setItem(row, 1, name)

    # --- дії над класом ---

    def _on_edit_class(self) -> None:
        dialog = ClassDialog(self.teacher_id, self._current_class, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_detail()

    def _on_remove_class(self) -> None:
        info = self._current_class
        if self._removal_mode == "archive":
            text = (
                f"Перенести клас «{info.name}» в архів? "
                "Журнали та оцінки збережуться, клас можна буде повернути."
            )
            if not self._confirm(text, "Архівувати"):
                return
            ok, _ = self._call(lambda s: s.set_class_archived(self.teacher_id, info.id, True))
        else:
            text = (
                f"Видалити клас «{info.name}» разом зі списком учнів ({info.student_count})? "
                "Цю дію не можна скасувати."
            )
            if not self._confirm(text, "Видалити"):
                return
            ok, _ = self._call(lambda s: s.delete_class(self.teacher_id, info.id))
        if ok:
            self.show_list()
        else:
            self._reload_detail()

    def _on_restore_class(self) -> None:
        info = self._current_class
        ok, _ = self._call(lambda s: s.set_class_archived(self.teacher_id, info.id, False))
        if ok:
            self._reload_detail()

    # --- дії над учнями ---

    def _on_add_student(self) -> None:
        dialog = StudentDialog(self.teacher_id, self._current_class.id, parent=self)
        dialog.exec()
        if dialog.changed:  # «Додати ще» міг додати учнів, навіть якщо діалог закрито хрестиком
            self._reload_detail()

    def _on_import(self) -> None:
        dialog = ImportStudentsDialog(self.teacher_id, self._current_class.id, parent=self)
        dialog.exec()
        if dialog.changed:
            self._reload_detail()

    def _selected_student(self) -> StudentInfo | None:
        rows = self.table.selectionModel().selectedRows()
        return self._students[rows[0].row()] if rows else None

    def _update_student_buttons(self) -> None:
        student = self._selected_student()
        self.edit_student_btn.setEnabled(student is not None)
        self.remove_student_btn.setEnabled(student is not None)
        self.remove_student_btn.setText("Повернути" if student and student.archived else "Прибрати")

    def _on_double_click(self, row: int, _column: int) -> None:
        student = self._students[row]
        if not student.archived and not self._current_class.archived:
            self._rename_student(student)

    def _on_edit_student(self) -> None:
        student = self._selected_student()
        if student is not None:
            self._rename_student(student)

    def _rename_student(self, student: StudentInfo) -> None:
        dialog = StudentDialog(self.teacher_id, self._current_class.id, student, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_detail()

    def _on_remove_student(self) -> None:
        student = self._selected_student()
        if student is None:
            return
        if student.archived:  # для вибулого ця кнопка — «Повернути»
            ok, _ = self._call(lambda s: s.set_student_archived(self.teacher_id, student.id, False))
            if ok:
                self._reload_detail()
            return

        ok, mode = self._call(lambda s: s.student_removal_mode(self.teacher_id, student.id))
        if not ok:
            return
        if mode == "delete":
            text = f"Прибрати учня «{student.full_name}» зі списку класу?"
            if not self._confirm(text, "Прибрати"):
                return
            ok, _ = self._call(lambda s: s.delete_student(self.teacher_id, student.id))
        else:
            text = (
                f"Учень «{student.full_name}» має оцінки чи відмітки. Позначити як вибулого? "
                "Оцінки збережуться, учня можна буде повернути."
            )
            if not self._confirm(text, "Позначити"):
                return
            ok, _ = self._call(lambda s: s.set_student_archived(self.teacher_id, student.id, True))
        if ok:
            self._reload_detail()

    def _on_table_menu(self, _pos) -> None:
        """Контекстне меню рядка (ті самі дії, що й кнопки під таблицею)."""
        item = self.table.itemAt(self.table.viewport().mapFromGlobal(QCursor.pos()))
        if item is None or self._current_class.archived:
            return
        self.table.selectRow(item.row())
        student = self._students[item.row()]
        menu = QMenu(self)
        rename = menu.addAction("Змінити")
        remove = menu.addAction("Повернути" if student.archived else "Прибрати")
        chosen = menu.exec(QCursor.pos())
        if chosen is rename:
            self._on_edit_student()
        elif chosen is remove:
            self._on_remove_student()

    # ------------------------------------------------------------------
    # Тема
    # ------------------------------------------------------------------

    def refresh_icons(self) -> None:
        """Перемальовує іконки та кольори, заданий програмно, після зміни теми."""
        for refresh in self._icon_refreshers:
            refresh()
        if self._current_class is not None:
            self._fill_table()  # приглушений колір вибулих учнів береться з активної теми

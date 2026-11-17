"""Діалоги сторінки «Класи»: клас, учень, імпорт списку учнів."""
from collections.abc import Callable
from datetime import date
from html.parser import HTMLParser
from typing import Any

from PySide6.QtCore import QMimeData, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from journal.services.class_service import (
    MAX_CLASS_NAME,
    MAX_STUDENT_NAME,
    ClassError,
    ClassInfo,
    ClassService,
    StudentInfo,
    default_school_year,
    school_year_choices,
)
from journal.services.grid_text import plural
from journal.ui.service_scope import service_scope
from journal.ui.widgets import FormDialog, button, field, label


class _ClassDialogBase(FormDialog):
    """Спільна основа: заголовок, рядок помилки та безпечний виклик ClassService."""

    def __init__(self, title: str, teacher_id: int, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.teacher_id = teacher_id

    def run_service(self, action: Callable[[ClassService], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат)."""

        def call():
            with service_scope(ClassService) as service:
                return action(service)

        return self.run(call, ClassError, "Помилка під час роботи з класами")

    @staticmethod
    def _edit(placeholder: str, max_length: int, edit_class: type[QLineEdit] = QLineEdit) -> QLineEdit:
        edit = edit_class()
        edit.setPlaceholderText(placeholder)
        edit.setMaxLength(max_length)
        return edit


class ClassDialog(_ClassDialogBase):
    """Створення або редагування класу (class_info=None — створення)."""

    def __init__(
        self, teacher_id: int, class_info: ClassInfo | None = None, parent: QWidget | None = None
    ) -> None:
        editing = class_info is not None
        super().__init__("Редагування класу" if editing else "Новий клас", teacher_id, parent)
        self.class_info = class_info
        self.result_info: ClassInfo | None = None

        self.name_edit = self._edit("напр. 9-А", MAX_CLASS_NAME)
        self.year_combo = QComboBox()
        today = date.today()
        years = school_year_choices(today)
        selected = default_school_year(today)
        if class_info is not None:
            # Рік класу може бути поза списком (старий клас) — додаємо його, щоб не втратити.
            if class_info.school_year not in years:
                years.append(class_info.school_year)
                years.sort()
            selected = class_info.school_year
            self.name_edit.setText(class_info.name)
        self.year_combo.addItems(years)
        self.year_combo.setCurrentText(selected)

        self.body.addWidget(field("НАЗВА КЛАСУ", self.name_edit))
        self.body.addWidget(field("НАВЧАЛЬНИЙ РІК", self.year_combo))
        self.body.addWidget(self.error_label)
        self.add_submit("Зберегти" if editing else "Створити", self._on_submit)

    def _on_submit(self) -> None:
        name, year = self.name_edit.text(), self.year_combo.currentText()
        if self.class_info is None:
            ok, info = self.run_service(lambda s: s.create_class(self.teacher_id, name, year))
        else:
            class_id = self.class_info.id
            ok, info = self.run_service(
                lambda s: s.update_class(self.teacher_id, class_id, name, year)
            )
        if ok:
            self.result_info = info
            self.accept()


class _HtmlLines(HTMLParser):
    """HTML → рядки тексту: кожен <tr> — один рядок (клітинки через Tab), <p>/<br>/<li>/<div> — розрив."""

    _BREAKS = ("br", "p", "div", "li")
    _SKIPPED = ("style", "script", "head", "title")

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self._cells: list[str] = []
        self._buffer: list[str] = []
        self._rows = 0  # глибина вкладення <tr>
        self._skip = 0

    def _end_cell(self) -> None:
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if text:
            self._cells.append(text)

    def end_line(self) -> None:
        self._end_cell()
        if self._cells:
            self.lines.append("\t".join(self._cells))
        self._cells = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIPPED:
            self._skip += 1
        elif tag == "tr":
            self.end_line()
            self._rows += 1
        elif tag in ("td", "th"):
            self._end_cell()
        elif tag in self._BREAKS:
            if self._rows:
                self._buffer.append(" ")
            else:
                self.end_line()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag == "tr":
            self.end_line()
            self._rows = max(0, self._rows - 1)
        elif tag in ("td", "th"):
            self._end_cell()
        elif tag in self._BREAKS and not self._rows:
            self.end_line()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buffer.append(data)


def mime_to_text(mime: QMimeData) -> str:
    """Текст із буфера обміну: text/plain, а якщо його немає (напр. таблиця Word) — з text/html."""
    if mime.hasText() and mime.text().strip():
        return mime.text()
    if mime.hasHtml():
        parser = _HtmlLines()
        parser.feed(mime.html())
        parser.close()
        parser.end_line()
        return "\n".join(parser.lines)
    return ""


class _ImportTextEdit(QPlainTextEdit):
    """Поле списку: приймає вставку й з HTML-буфера; якщо тексту не вдалося дістати — сигнал."""

    paste_failed = Signal()

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasText() or source.hasHtml()

    def insertFromMimeData(self, source: QMimeData) -> None:
        text = mime_to_text(source)
        if text:
            self.insertPlainText(text)
        else:
            self.paste_failed.emit()


class _PasteLineEdit(QLineEdit):
    """Поле імені: вставка 2+ непорожніх рядків не склеюється в одне ім'я, а віддається сигналом."""

    list_pasted = Signal(str)

    def paste(self) -> None:
        text = mime_to_text(QGuiApplication.clipboard().mimeData())
        if sum(1 for line in text.splitlines() if line.strip()) >= 2:
            self.list_pasted.emit(text)
        else:
            self.insert(" ".join(text.split()))

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paste_menu(self) -> QMenu:
        # Власне меню: стандартний пункт «Вставити» не викликає paste(), а розпізнати його не можна.
        menu = QMenu(self)
        has_selection = self.hasSelectedText()
        for text, slot, enabled in (
            ("Вирізати", self.cut, has_selection),
            ("Копіювати", self.copy, has_selection),
            ("Вставити", self.paste, not self.isReadOnly()),
            ("Виділити все", self.selectAll, bool(self.text())),
        ):
            menu.addAction(text, slot).setEnabled(enabled)
        return menu

    def contextMenuEvent(self, event) -> None:
        menu = self.paste_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()


class StudentDialog(_ClassDialogBase):
    """Додавання (з кнопкою «Додати ще») або перейменування одного учня."""

    def __init__(
        self,
        teacher_id: int,
        class_id: int,
        student: StudentInfo | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Новий учень" if student is None else "Редагування учня", teacher_id, parent)
        self.class_id = class_id
        self.student = student
        self.changed = False  # чи було щось додано/змінено (для оновлення списку на сторінці)

        self.name_edit = self._edit(
            "Коваленко Олена", MAX_STUDENT_NAME, _PasteLineEdit if student is None else QLineEdit
        )
        if student is not None:
            self.name_edit.setText(student.full_name)
        else:
            self.name_edit.list_pasted.connect(self._on_list_pasted)
        self.body.addWidget(field("ПРІЗВИЩЕ ТА ІМ'Я", self.name_edit))
        if student is None:
            self.body.addWidget(
                label(
                    "Можна вставити одразу весь список — кожен учень з нового рядка.",
                    muted=True,
                    wrap=True,
                )
            )

        # Невелика примітка після «Додати ще»
        self.note_label = label("", muted=True)
        self.note_label.hide()
        self.body.addWidget(self.note_label)
        self.body.addWidget(self.error_label)

        if student is None:
            row = QHBoxLayout()
            row.setSpacing(10)
            add_more = button("Додати ще")
            add_more.setMinimumHeight(40)
            add_more.clicked.connect(self._on_add_more)
            row.addWidget(add_more)
            self.add_submit("Додати", self._on_add, row)
            row.setStretch(1, 1)
            self.body.addLayout(row)
        else:
            self.add_submit("Зберегти", self._on_rename)

    def _add(self) -> StudentInfo | None:
        text = self.name_edit.text()
        ok, info = self.run_service(lambda s: s.add_student(self.teacher_id, self.class_id, text))
        if ok:
            self.changed = True
            return info
        return None

    def _on_add(self) -> None:
        if self._add() is not None:
            self.accept()

    def _on_add_more(self) -> None:
        info = self._add()
        if info is not None:
            self.note_label.setText(f"Додано: {info.full_name}")
            self.note_label.show()
            self.name_edit.clear()
            self.name_edit.setFocus()

    def _on_list_pasted(self, text: str) -> None:
        dialog = ImportStudentsDialog(self.teacher_id, self.class_id, text, parent=self)
        dialog.exec()
        if dialog.changed:
            self.changed = True
            self.accept()
        else:
            self.name_edit.clear()

    def _on_rename(self) -> None:
        student_id = self.student.id
        text = self.name_edit.text()
        ok, _ = self.run_service(lambda s: s.rename_student(self.teacher_id, student_id, text))
        if ok:
            self.changed = True
            self.accept()


class ImportStudentsDialog(_ClassDialogBase):
    """Імпорт списку учнів зі вставленого тексту з живою підказкою."""

    PREVIEW_DELAY_MS = 300

    def __init__(
        self, teacher_id: int, class_id: int, initial_text: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__("Додати учнів списком", teacher_id, parent)
        self.setMinimumWidth(520)
        self.class_id = class_id
        self.changed = False

        self.body.addWidget(
            label(
                "Вставте список — один учень у рядку. Номери на початку рядка буде прибрано.",
                muted=True,
                wrap=True,
            )
        )
        self.text_edit = _ImportTextEdit()
        self.text_edit.setPlaceholderText("1. Коваленко Олена\n2. Шевченко Іван")
        self.text_edit.setMinimumHeight(220)
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setTabChangesFocus(True)  # Tab веде до кнопок, а не вставляє табуляцію
        self.body.addWidget(self.text_edit)

        self.paste_hint = label("Не вдалося вставити: скопіюйте список як текст", muted=True)
        self.paste_hint.hide()
        self.text_edit.paste_failed.connect(self.paste_hint.show)
        self.text_edit.textChanged.connect(self.paste_hint.hide)
        self.body.addWidget(self.paste_hint)

        self.preview_label = label("", muted=True)
        self.body.addWidget(self.preview_label)
        self.body.addWidget(self.error_label)

        self.submit_button = self.add_submit("Додати учнів", self._on_submit, default=False)

        # Debounce: підказку оновлюємо через 300 мс після останнього натискання клавіші.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self.update_preview)
        self.text_edit.textChanged.connect(self._timer.start)
        self.update_preview()

    def update_preview(self) -> None:
        """Підрахунок «що буде додано» без запису в БД."""
        text = self.text_edit.toPlainText()
        ok, result = self.run_service(
            lambda s: s.preview_import(self.teacher_id, self.class_id, text)
        )
        if ok:
            self.preview_label.setText(
                f"Буде додано: {result.added} · дублікатів пропущено: {result.skipped_duplicates}"
            )
            self.submit_button.setEnabled(result.added > 0)
        else:
            self.preview_label.setText("")
            self.submit_button.setEnabled(False)

    def _on_submit(self) -> None:
        text = self.text_edit.toPlainText()
        ok, result = self.run_service(
            lambda s: s.import_students(self.teacher_id, self.class_id, text)
        )
        if not ok:
            return
        self.changed = True
        QMessageBox.information(
            self,
            "Імпорт завершено",
            f"Додано {result.added} {plural(result.added, 'учня', 'учні', 'учнів')}. "
            f"Пропущено дублікатів: {result.skipped_duplicates}.",
        )
        self.accept()
